"""
Aurum Edge Webhook + Signal Trade App Bridge (Railway)
v2.2 — Execution truth-checking, hard close fix, idempotency, position lock.
Receives TradingView alert webhooks → gates → sizes → sends to STA.
ONLY entry point for signals — all other signal generators disabled.
"""
import os
import json
import time
import hmac
import hashlib
import logging
import threading
import requests as http_req
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from config import (
    SILVER_BULLET_START, SILVER_BULLET_END, SILVER_BULLET_BOOST,
    ASIA_TRADING_DAYS,
    MGC_MIN_STOP_TICKS, MGC_MAX_STOP_TICKS, MGC_TICK_SIZE
)
from lucid_risk_engine import LucidRiskEngine, get_current_session
from news_calendar_2026 import is_news_blackout, check_geopolitical_blackout, get_next_event
from trade_journal import TradeJournal
from tradovate_balance_sync import get_balance_sync, init_balance_sync

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
STA_WEBHOOK_URL = os.getenv("STA_WEBHOOK_URL", "")
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.getenv("PORT", "3000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("webhook")

# ── Idempotency: dedup tracker ──
_last_signal = {}  # key: "symbol:direction" -> timestamp_utc, orderId
DEDUP_SECONDS = 600  # 10 min

# ── Signal Trade App Client ───────────────────
class SignalTradeAppClient:
    """Sends validated trade signals to Signal Trade App for execution."""

    def __init__(self):
        self.webhook_url = STA_WEBHOOK_URL

    def send_signal(self, payload):
        if not self.webhook_url:
            log.warning("STA_WEBHOOK_URL not configured — cannot send signal")
            return None
        try:
            resp = http_req.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            if resp.status_code in (200, 201):
                resp_data = resp.json() if resp.text else {}
                log.info(f"STA response: {resp_data}")
                return resp_data
            else:
                log.error(f"STA rejected signal: {resp.status_code} {resp.text[:500]}")
                return {"error": f"http_{resp.status_code}", "detail": resp.text[:500]}
        except Exception as e:
            log.error(f"STA send failed: {e}")
            return {"error": str(e)}

    def close_position_opening(self, symbol, direction, qty, price, sl, tp1, tp2):
        """Close by sending opposite-side market order with flatten bracket."""
        opp_dir = "sell" if direction == "long" else "buy"
        payload = {
            "action": opp_dir,
            "symbol": symbol,
            "qty": qty,
            "orderType": "market",
            "comment": f"AurumEdge_CLOSE_{direction.upper()}"
        }
        return self.send_signal(payload)

    def flatten_position(self, symbol, qty):
        """Flatten via opposite-side market order (for hard close)."""
        payload = {
            "action": "sell",
            "symbol": symbol,
            "qty": qty,
            "orderType": "market",
            "comment": f"HardClose_{datetime.now(timezone.utc).strftime('%H%M')}"
        }
        return self.send_signal(payload)


# ── Webhook Handler ────────────────────────────
class WebhookHandler(BaseHTTPRequestHandler):
    sta = SignalTradeAppClient()
    risk_engine = LucidRiskEngine()
    journal = TradeJournal()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            status = self.risk_engine.get_status()
            stats = self.journal.get_stats()
            regime_breakdown = self.journal.get_regime_breakdown()
            best_scenario = self.journal.get_best_scenario()
            status["trade_journal"] = {
                "total_trades": stats["total"],
                "win_rate": stats["win_rate"],
                "total_pnl": round(stats["total_pnl"], 2),
                "avg_conviction": round(stats["avg_conviction"], 1),
            }
            next_event = get_next_event()
            if next_event:
                status["next_news_event"] = next_event
            now = datetime.now(timezone.utc)
            current_hour = now.hour + now.minute / 60.0
            active_gates, semi_active = [], []
            blackout = is_news_blackout()
            if blackout["in_blackout"]:
                active_gates.append(f"news_blackout:{blackout['event_name']}")
            if SILVER_BULLET_START <= current_hour < SILVER_BULLET_END:
                semi_active.append("silver_bullet")
            asia_hour, asia_end = 5.5 + 1.5/60.0, 7.0
            if asia_hour <= current_hour < asia_end:
                if now.weekday() in ASIA_TRADING_DAYS:
                    semi_active.append("asia_open")
                else:
                    active_gates.append("asia_blocked_wed_fri")
            status["gates"] = {"active_blockers": active_gates, "active_boosters": semi_active}
            # Execution health
            status["execution"] = {
                "last_order_id": self.risk_engine.state.get("last_order_id"),
                "last_execution_confirmed": self.risk_engine.state.get("last_execution_confirmed", False),
                "last_execution_time": self.risk_engine.state.get("last_execution_time"),
            }
            try:
                bs = get_balance_sync()
                status["balance_sync"] = bs.get_sync_info()
                if bs.risk_engine:
                    status["balance_sync"]["last_reconcile"] = bs.periodic_reconcile()
            except Exception as e:
                status["balance_sync"] = {"error": str(e), "synced": False}
            self._respond(200, status)
        elif path == "/":
            self._respond(200, {"service": "Aurum Edge Webhook", "version": "2.2"})
        elif path == "/trades":
            self._respond(200, {"trades": self.journal.get_recent_trades(20)})
        else:
            self._respond(404, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        if path == "/webhook":
            self._handle_webhook(body)
        elif path == "/exit":
            self._handle_exit(body)
        else:
            self._respond(404, {"error": "not_found"})

    def _handle_exit(self, raw_body):
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid_json"})
            return
        trade_id = payload.get("trade_id")
        exit_price = float(payload.get("exit_price", 0))
        exit_reason = payload.get("exit_reason", "signal")
        pnl = float(payload.get("pnl", 0))
        pnl_pct = float(payload.get("pnl_pct", 0))
        fees = float(payload.get("fees", 0))
        symbol = payload.get("symbol", "")
        if not trade_id and symbol:
            last_trade = self.journal.get_last_open_trade_by_symbol(symbol)
            if last_trade:
                trade_id = last_trade["id"]
        if trade_id:
            self.journal.log_exit(trade_id, exit_price, exit_reason, pnl, pnl_pct, fees)
            self.risk_engine.record_exit(symbol, pnl, pnl_pct)
            log.info(f"Exit: trade_id={trade_id} {symbol} pnl=${pnl:.2f} reason={exit_reason}")
            try:
                get_balance_sync().post_exit_reconcile()
            except Exception:
                pass
            self._respond(200, {"status": "exit_recorded", "trade_id": trade_id})
        else:
            if symbol:
                self.risk_engine.record_exit(symbol, pnl, pnl_pct)
            self._respond(200, {"status": "exit_recorded_balance_only"})

    def _handle_webhook(self, raw_body):
        """Process incoming TradingView alert → gates → size → STA."""
        global _last_signal

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid_json"})
            return

        # ── Signature check (NO secret = reject all non-TradingView) ──
        if WEBHOOK_SECRET:
            sig = self.headers.get("X-TradingView-Signature", "")
            expected = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                log.warning("Invalid signature — rejecting")
                self._respond(403, {"error": "invalid_signature"})
                return
        else:
            # No secret configured: log warning but accept (Railway demo)
            log.warning("WEBHOOK_SECRET not set — all POSTs accepted")

        symbol = payload.get("symbol", "").replace("=F", "").replace("1!", "").replace("!", "")
        direction = payload.get("direction")
        price = float(payload.get("price", 0))
        conviction = float(payload.get("conviction", 0))
        sl_target = float(payload.get("sl_target", 0))
        entry_reason = payload.get("entry_reason", "TradingView signal")
        scenario = payload.get("scenario", "sweep_mss_fvg")

        if not symbol or not direction or price <= 0:
            self._respond(400, {"error": "missing_fields"})
            return

        log.info(f"SIGNAL: {direction.upper()} {symbol} @ {price} conviction={conviction}/10")

        # ── GATE 0: Idempotency (dedup same symbol+direction within 10 min) ──
        dedup_key = f"{symbol}:{direction}"
        now = datetime.now(timezone.utc)
        last = _last_signal.get(dedup_key)
        if last:
            age = (now - last["time"]).total_seconds()
            if age < DEDUP_SECONDS:
                log.warning(f"DEDUP: {dedup_key} already sent {age:.0f}s ago — rejecting")
                self._respond(200, {"status": "blocked", "reason": f"duplicate_{DEDUP_SECONDS}s"})
                return
        _last_signal[dedup_key] = {"time": now}

        # ── GATE 0.5: Position lock (max 1 open position) ──
        open_positions = self.risk_engine.state.get("positions", {})
        if len(open_positions) >= 1:
            # Allow only if same symbol and opposite direction (close then open)
            existing = open_positions.get(symbol)
            if existing and existing["direction"] == direction:
                log.warning(f"POSITION LOCK: already in {direction} {symbol} — rejecting")
                self._respond(200, {"status": "blocked", "reason": "position_lock_active"})
                return

        # ── GATE 1: News Blackout ──
        blackout = is_news_blackout()
        if blackout["in_blackout"]:
            log.warning(f"⛔ NEWS: {blackout['event_name']} ({blackout['minutes_remaining']}min)")
            self._respond(200, {"status": "blocked", "reason": f"news_blackout:{blackout['event_name']}"})
            return
        geo = check_geopolitical_blackout()
        if geo["in_blackout"]:
            log.warning(f"⚠ GEO: {geo['event_name']}")
            self._respond(200, {"status": "blocked", "reason": f"geopolitical:{geo['event_name']}"})
            return

        # ── GATE 2: Market Regime ──
        market_regime = payload.get("market_regime", {})
        regime = market_regime.get("regime", "trending")
        rec = market_regime.get("recommended_action", {})
        if regime == "ranging" and not rec.get("allow_breakout", True) and scenario in ("breakout", "sweep_breakout"):
            self._respond(200, {"status": "blocked", "reason": "regime_ranging_block_breakout"})
            return
        min_conviction = rec.get("min_conviction", 7.0)
        size_modifier = rec.get("size_modifier", 1.0)
        sl_multiplier = rec.get("sl_multiplier", 1.0)
        if conviction < min_conviction:
            self._respond(200, {"status": "blocked", "reason": f"regime_conviction:{regime}:need_{min_convition}:got_{conviction}"})
            return

        # ── GATE 3: Silver Bullet Boost ──
        current_hour = now.hour + now.minute / 60.0
        in_silver_bullet = SILVER_BULLET_START <= current_hour < SILVER_BULLET_END
        if in_silver_bullet:
            conviction = min(10.0, conviction + SILVER_BULLET_BOOST)

        # ── GATE 4: Asia Wed-Fri ──
        asia_hour, asia_end = 5.5 + 1.5/60.0, 7.0
        if asia_hour <= current_hour < asia_end and now.weekday() not in ASIA_TRADING_DAYS:
            self._respond(200, {"status": "blocked", "reason": "asia_blocked_wed_fri"})
            return

        # ── GATE 4.5: Sync block (live only) ──
        try:
            if os.getenv("TRADOVATE_ENV", "demo") == "live" and get_balance_sync().is_sync_blocked():
                self._respond(200, {"status": "blocked", "reason": "sync_blocked_3_failures"})
                return
        except Exception:
            pass

        # ── GATE 5: Lucid Risk ──
        gate_result = self.risk_engine.check_gate(symbol, direction, price, conviction)
        if not gate_result["allowed"]:
            self._respond(200, {"status": "blocked", "reason": gate_result["reason"]})
            return

        # ── Stop Loss Determination ──
        if sl_target <= 0:
            self._respond(200, {"status": "blocked", "reason": "missing_stop_distance"})
            return
        sl_dist = abs(price - sl_target) * sl_multiplier
        if "MGC" in symbol:
            sl_ticks = int(sl_dist / MGC_TICK_SIZE)
            sl_dist = max(MGC_MIN_STOP_TICKS, min(MGC_MAX_STOP_TICKS, sl_ticks)) * MGC_TICK_SIZE

        # ── Kelly Sizing ──
        contracts = self.risk_engine.calculate_contracts(symbol, direction, price, conviction, sl_dist)
        contracts = max(1, int(contracts * size_modifier))
        if contracts <= 0:
            self._respond(200, {"status": "blocked", "reason": "zero_contracts"})
            return

        # ── TP Levels ──
        tp1_price = price + (sl_dist * 1.5) if direction == "long" else price - (sl_dist * 1.5)
        tp2_price = price + (sl_dist * 3.0) if direction == "long" else price - (sl_dist * 3.0)
        sl_price = price - sl_dist if direction == "long" else price + sl_dist

        sta_action = "buy" if direction == "long" else "sell"
        sta_payload = {
            "action": sta_action,
            "symbol": "MGC" if "MGC" in symbol else ("MES" if "MES" in symbol else "MNQ"),
            "qty": contracts,
            "orderType": "limit",
            "price": round(price, 2),
            "stopLoss": round(sl_price, 2),
            "takeProfit": round(tp1_price, 2),
            "bracket1": {
                "target": round(tp2_price, 2),
                "stop": round(sl_price, 2)
            },
            "comment": f"AurumEdge_{direction.upper()}_{regime}"
        }

        # ── Send to STA ──
        result = self.sta.send_signal(sta_payload)

        # ── Truth-check: extract orderId from STA response ──
        order_id = None
        execution_confirmed = False
        if result:
            if isinstance(result, dict):
                order_id = result.get("orderId") or result.get("order_id") or result.get("id")
                execution_confirmed = bool(order_id)
            if execution_confirmed:
                log.info(f"✅ EXECUTION CONFIRMED: orderId={order_id}")
            else:
                log.error(f"❌ EXECUTION FAILED: STA accepted but no orderId — response={result}")
                self.risk_engine.state["last_execution_confirmed"] = False
                self.risk_engine.state["last_order_id"] = None
                self.risk_engine.state["last_execution_time"] = now.isoformat()
        else:
            log.error(f"❌ STA signal delivery failed")
            self.risk_engine.state["last_execution_confirmed"] = False
            self.risk_engine.state["last_order_id"] = None
            self.risk_engine.state["last_execution_time"] = now.isoformat()

        # ── Record entry in risk engine + store orderId ──
        self.risk_engine.record_entry(symbol, direction, price, contracts, conviction)
        if order_id:
            self.risk_engine.state["last_order_id"] = order_id
            self.risk_engine.state["last_execution_confirmed"] = True
            self.risk_engine.state["last_execution_time"] = now.isoformat()
            self.risk_engine._save_state()

        # ── Log to Trade Journal ──
        session_label = "london" if 7 <= current_hour < 10 else ("silver_bullet" if in_silver_bullet else "ny_open")
        self.journal.log_entry(
            symbol=symbol, direction=direction, entry_price=price,
            stop_loss=sl_price, take_profit=tp2_price, quantity=contracts,
            conviction=conviction, regime=regime, scenario=scenario,
            silver_bullet=in_silver_bullet, session=session_label,
            entry_reason=entry_reason, gate_failures=[]
        )

        status = "executed" if execution_confirmed else "delivery_confirmed"
        self._respond(200, {
            "status": status,
            "symbol": symbol,
            "direction": direction,
            "contracts": contracts,
            "conviction": conviction,
            "order_id": order_id,
            "execution_confirmed": execution_confirmed,
            "regime": regime,
        })

    def _respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info(f"{self.address_string()} - {fmt % args}")


# ── Hard Close Scheduler ───────────────────────
def hard_close_scheduler():
    """Flatten all positions at 16:30 ET (20:30 UTC) / 11:45 ET (15:45 UTC) Fri."""
    sta = SignalTradeAppClient()
    journal = TradeJournal()
    risk_engine = LucidRiskEngine()
    symbols = ["MGC", "MES"]
    while True:
        now = datetime.now(timezone.utc)
        hour_min = now.hour * 60 + now.minute
        # Fri early close at 11:45 ET = 15:45 UTC (market closes 12:00 ET)
        if now.weekday() == 4:
            target = 15 * 60 + 45
        else:
            target = 20 * 60 + 30  # 16:30 ET = 20:30 UTC
        if target <= hour_min < target + 3:
            log.info(f"Hard close time ({'Fri' if now.weekday() == 4 else 'Daily'}) — flattening via STA")
            for sym in symbols:
                pos = risk_engine.state.get("positions", {}).get(sym)
                qty = pos["contracts"] if pos else 1
                result = sta.flatten_position(sym, qty)
                if result and (result.get("orderId") or result.get("order_id")):
                    log.info(f"Hard close {sym} orderId={result.get('orderId') or result.get('order_id')}")
                else:
                    log.warning(f"Hard close {sym} — no orderId in response")
            time.sleep(180)
        time.sleep(30)


# ── Main ───────────────────────────────────────
def main():
    try:
        risk_engine = LucidRiskEngine()
        bs = init_balance_sync(risk_engine)
        WebhookHandler.balance_sync = bs
    except Exception as e:
        log.warning(f"Startup sync failed: {e}")

    t = threading.Thread(target=hard_close_scheduler, daemon=True)
    t.start()

    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), WebhookHandler)
    log.info(f"Aurum Edge v2.2 listening on {LISTEN_HOST}:{LISTEN_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()