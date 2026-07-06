"""
Aurum Edge Webhook + Signal Trade App Bridge (Railway)
Receives TradingView alert webhooks → news blackout gate → regime gate
→ validates via Lucid Risk Engine → sends validated signals to Signal Trade App.
Also handles health checks, hard close, and evaluation status.
v2.1 — Session info in health, fixed exit tracking, resilient state.
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

# ── Config (direct imports) ────────────────────
from config import (
    SILVER_BULLET_START, SILVER_BULLET_END, SILVER_BULLET_BOOST,
    ASIA_TRADING_DAYS,
    MGC_MIN_STOP_TICKS, MGC_MAX_STOP_TICKS, MGC_TICK_SIZE
)

# ── Modules ────────────────────────────────────
from lucid_risk_engine import LucidRiskEngine, get_current_session
from news_calendar_2026 import is_news_blackout, check_geopolitical_blackout, get_next_event
from trade_journal import TradeJournal
from tradovate_balance_sync import get_balance_sync, init_balance_sync

# ── Config ─────────────────────────────────────
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
STA_WEBHOOK_URL = os.getenv("STA_WEBHOOK_URL", "")
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.getenv("PORT", "3000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("webhook")

# ── Signal Trade App Client ───────────────────
class SignalTradeAppClient:
    """Sends validated trade signals to Signal Trade App for execution."""

    def __init__(self):
        self.webhook_url = STA_WEBHOOK_URL

    def send_signal(self, payload):
        """Forward a trade signal to the Signal Trade App webhook endpoint."""
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
                log.info(f"Signal sent to STA: {payload.get('direction')} {payload.get('symbol')} -> {resp.status_code}")
                return resp.json() if resp.text else {"status": "ok"}
            else:
                log.error(f"STA rejected signal: {resp.status_code} {resp.text[:200]}")
                return None
        except Exception as e:
            log.error(f"STA send failed: {e}")
            return None

    def close_position(self, symbol):
        """Signal to close/exit a position on Signal Trade App."""
        payload = {
            "action": "close",
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat()
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
            # Enrich with trade journal stats
            stats = self.journal.get_stats()
            regime_breakdown = self.journal.get_regime_breakdown()
            best_scenario = self.journal.get_best_scenario()
            status["trade_journal"] = {
                "total_trades": stats["total"],
                "win_rate": stats["win_rate"],
                "total_pnl": round(stats["total_pnl"], 2),
                "avg_conviction": round(stats["avg_conviction"], 1),
                "best_trade": round(stats["best_trade"], 2),
                "worst_trade": round(stats["worst_trade"], 2),
                "current_streak": "N/A",
                "best_scenario": best_scenario,
                "regime_breakdown": regime_breakdown,
            }
            # Enrich with next news event
            next_event = get_next_event()
            if next_event:
                status["next_news_event"] = next_event
            # Add active gates summary
            now = datetime.now(timezone.utc)
            current_hour = now.hour + now.minute / 60.0
            active_gates = []
            blackout = is_news_blackout()
            if blackout["in_blackout"]:
                active_gates.append(f"news_blackout:{blackout['event_name']}")
            semi_active = []
            if SILVER_BULLET_START <= current_hour < SILVER_BULLET_END:
                semi_active.append("silver_bullet")
            asia_hour = 5.5 + 1.5/60.0
            asia_end = 7.0
            if asia_hour <= current_hour < asia_end:
                if now.weekday() in ASIA_TRADING_DAYS:
                    semi_active.append("asia_open")
                else:
                    active_gates.append("asia_blocked_wed_fri")
            status["gates"] = {
                "active_blockers": active_gates,
                "active_boosters": semi_active,
            }

            # Add balance sync info
            try:
                bs = get_balance_sync()
                status["balance_sync"] = bs.get_sync_info()
                # Periodic reconcile (non-blocking)
                if bs.risk_engine:
                    sync_result = bs.periodic_reconcile()
                    status["balance_sync"]["last_reconcile"] = sync_result
            except Exception as e:
                status["balance_sync"] = {"error": str(e), "synced": False}

            self._respond(200, status)
        elif path == "/":
            self._respond(200, {"service": "Aurum Edge Webhook", "version": "2.0"})
        elif path == "/trades":
            recent = self.journal.get_recent_trades(20)
            self._respond(200, {"trades": recent})
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
        """Record a trade exit (called by Signal Trade App or hard close)."""
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

        # If no trade_id, look up the last open trade for this symbol
        if not trade_id and symbol:
            last_trade = self.journal.get_last_open_trade_by_symbol(symbol)
            if last_trade:
                trade_id = last_trade["id"]
                log.info(f"Resolved trade_id={trade_id} for {symbol} from last open trade")

        if trade_id:
            self.journal.log_exit(trade_id, exit_price, exit_reason, pnl, pnl_pct, fees)
            self.risk_engine.record_exit(symbol, pnl, pnl_pct)
            log.info(f"Exit recorded: trade_id={trade_id} {symbol} pnl=${pnl:.2f} reason={exit_reason}")

            # Post-exit balance reconcile
            try:
                bs = get_balance_sync()
                bs.post_exit_reconcile()
            except Exception as e:
                log.warning(f"Post-exit reconcile failed (non-fatal): {e}")

            self._respond(200, {"status": "exit_recorded", "trade_id": trade_id})
        else:
            log.warning(f"Exit for {symbol} — no trade_id provided and no open trade found")
            # Still record PnL in risk engine for balance tracking
            if symbol:
                self.risk_engine.record_exit(symbol, pnl, pnl_pct)
                log.info(f"Exit recorded in risk engine only: {symbol} pnl=${pnl:.2f}")
            self._respond(200, {"status": "exit_recorded_balance_only"})

    def _handle_webhook(self, raw_body):
        """Process incoming TradingView alert and forward to STA."""
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid_json"})
            return

        # Validate signature if secret set
        if WEBHOOK_SECRET:
            sig = self.headers.get("X-TradingView-Signature", "")
            expected = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                self._respond(403, {"error": "invalid_signature"})
                return

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

        log.info(f"Signal: {direction.upper()} {symbol} @ {price} (conviction: {conviction}/10)")

        # ═══════════════════════════════════════════
        # GATE 1: News Blackout (First gate!)
        # ═══════════════════════════════════════════
        blackout = is_news_blackout()
        if blackout["in_blackout"]:
            log.warning(f"⛔ NEWS BLACKOUT: {blackout['event_name']} ({blackout['minutes_remaining']}min remaining)")
            self._respond(200, {"status": "blocked", "reason": f"news_blackout:{blackout['event_name']}"})
            return

        # Check geopolitical deviation
        geo_blackout = check_geopolitical_blackout()
        if geo_blackout["in_blackout"]:
            log.warning(f"⚠ GEOPOLITICAL BLACKOUT: {geo_blackout['event_name']}")
            self._respond(200, {"status": "blocked", "reason": f"geopolitical:{geo_blackout['event_name']}"})
            return

        # ═══════════════════════════════════════════
        # GATE 2: Market Regime Gate
        # ═══════════════════════════════════════════
        market_regime = payload.get("market_regime", {})
        regime = market_regime.get("regime", "trending")
        recommended_action = market_regime.get("recommended_action", {})

        # If ranging, only allow FVG reversion entries (breakout blocked)
        if regime == "ranging" and not recommended_action.get("allow_breakout", True):
            # Check if this is a breakout setup — block it
            if scenario in ("breakout", "sweep_breakout"):
                log.warning(f"⛔ REGIME GATE: Ranging market — breakout entries blocked")
                self._respond(200, {"status": "blocked", "reason": "regime_ranging_block_breakout"})
                return

        # If volatile, require higher conviction
        min_conviction = recommended_action.get("min_conviction", 7.0)
        size_modifier = recommended_action.get("size_modifier", 1.0)
        sl_multiplier = recommended_action.get("sl_multiplier", 1.0)

        if conviction < min_conviction:
            log.warning(f"⛔ REGIME GATE: {regime} market requires {min_conviction}+ conviction (got {conviction})")
            self._respond(200, {"status": "blocked", "reason": f"regime_conviction:{regime}:need_{min_conviction}:got_{conviction}"})
            return

        # ═══════════════════════════════════════════
        # GATE 3: Silver Bullet Boost
        # ═══════════════════════════════════════════
        now_utc = datetime.now(timezone.utc)
        current_hour = now_utc.hour + now_utc.minute / 60.0
        in_silver_bullet = SILVER_BULLET_START <= current_hour < SILVER_BULLET_END
        if in_silver_bullet:
            conviction = min(10.0, conviction + SILVER_BULLET_BOOST)
            log.info(f"Silver Bullet window active — conviction boosted to {conviction}/10")

        # ═══════════════════════════════════════════
        # GATE 4: Asia Wed-Fri Gate
        # ═══════════════════════════════════════════
        asia_hour = 5.5 + 1.5/60.0  # 1:30 AM ET = 5:30 UTC
        asia_end = 7.0  # 3:00 AM ET = 7:00 UTC
        in_asia_window = asia_hour <= current_hour < asia_end
        if in_asia_window and now_utc.weekday() not in ASIA_TRADING_DAYS:
            log.warning(f"Asia window blocked — {now_utc.strftime('%A')} not in trading days {ASIA_TRADING_DAYS}")
            self._respond(200, {"status": "blocked", "reason": "asia_blocked_wed_fri"})
            return

        # ═══════════════════════════════════════════
        # GATE 4.5: Balance Sync Block Check
        # ═══════════════════════════════════════════
        try:
            bs = get_balance_sync()
            if bs.is_sync_blocked():
                log.warning("⛔ SYNC BLOCKED: 3+ consecutive balance sync failures — new entries blocked")
                self._respond(200, {"status": "blocked", "reason": "sync_blocked_3_failures"})
                return
        except Exception as e:
            log.warning(f"Sync gate check failed (non-fatal): {e}")

        # ═══════════════════════════════════════════
        # GATE 5: Lucid Risk Gate
        # ═══════════════════════════════════════════
        gate_result = self.risk_engine.check_gate(symbol, direction, price, conviction)
        if not gate_result["allowed"]:
            log.warning(f"GATE BLOCKED: {gate_result['reason']}")
            self._respond(200, {"status": "blocked", "reason": gate_result["reason"]})
            return

        # ═══════════════════════════════════════════
        # Stop Loss Determination (before sizing)
        # ═══════════════════════════════════════════
        if sl_target <= 0:
            log.warning(f"⛔ Missing stop distance in signal — rejecting {symbol} {direction}")
            self._respond(200, {"status": "blocked", "reason": "missing_stop_distance"})
            return

        sl_dist = abs(price - sl_target)
        if sl_dist <= 0:
            log.warning(f"⛔ Invalid stop distance (zero) — rejecting {symbol} {direction}")
            self._respond(200, {"status": "blocked", "reason": "invalid_stop_distance"})
            return

        # Apply regime SL multiplier
        sl_dist = sl_dist * sl_multiplier

        # MGC Stop Widening (min 20 ticks, max 40 ticks)
        if "MGC" in symbol:
            sl_ticks = int(sl_dist / MGC_TICK_SIZE)
            if sl_ticks < MGC_MIN_STOP_TICKS:
                sl_dist = MGC_MIN_STOP_TICKS * MGC_TICK_SIZE
                log.info(f"MGC stop widened to {MGC_MIN_STOP_TICKS} ticks ({sl_dist})")
            elif sl_ticks > MGC_MAX_STOP_TICKS:
                sl_dist = MGC_MAX_STOP_TICKS * MGC_TICK_SIZE
                log.info(f"MGC stop capped at {MGC_MAX_STOP_TICKS} ticks ({sl_dist})")

        # ═══════════════════════════════════════════
        # Kelly Criterion Sizing (with regime modifier + actual stop)
        # ═══════════════════════════════════════════
        contracts = self.risk_engine.calculate_contracts(symbol, direction, price, conviction, sl_dist)
        # Apply regime size modifier (e.g. 0.5 for volatile)
        contracts = max(1, int(contracts * size_modifier))
        if contracts <= 0:
            log.warning("Sizing returned 0 contracts — aborting")
            self._respond(200, {"status": "blocked", "reason": "zero_contracts"})
            return

        # Log full sizing decision for audit
        log.info(f"SIZING: entry={price} stop={sl_dist} dist_ticks={int(sl_dist/0.10 if 'MGC' in symbol else sl_dist/0.25)} "
                 f"risk$={self.risk_engine.state['balance'] * self.risk_engine._kelly_criterion(conviction):.2f} "
                 f"per_contract$={sl_dist * 10.0:.2f} contracts={contracts} "
                 f"capped={'yes' if contracts >= (8 if 'MGC' in symbol else 6) else 'no'}")

        # ═══════════════════════════════════════════
        # TP Levels (using actual sl_dist)
        # ═══════════════════════════════════════════
        tp1_price = price + (sl_dist * 1.5) if direction == "long" else price - (sl_dist * 1.5)
        tp2_price = price + (sl_dist * 3.0) if direction == "long" else price - (sl_dist * 3.0)

        # ═══════════════════════════════════════════
        # Build STA signal payload
        # ═══════════════════════════════════════════
        part_size = max(1, contracts // 3)
        remaining = contracts - (2 * part_size)
        sl_price = price - sl_dist if direction == "long" else price + sl_dist

        sta_action = "buy" if direction == "long" else "sell"
        sta_payload = {
            "action": sta_action,
            "symbol": "MGC" if "MGC" in symbol else "MES",
            "qty": contracts,
            "orderType": "limit",
            "price": price,
            "stopLoss": sl_price,
            "takeProfit": round(tp1_price, 2),
            "bracket1": {
                "target": round(tp2_price, 2),
                "stop": sl_price
            },
            "comment": f"AurumEdge_{direction.upper()}_{regime}"
        }

        # ═══════════════════════════════════════════
        # Send to Signal Trade App
        # ═══════════════════════════════════════════
        result = self.sta.send_signal(sta_payload)
        self.risk_engine.record_entry(symbol, direction, price, contracts, conviction)

        # ═══════════════════════════════════════════
        # Log to Trade Journal
        # ═══════════════════════════════════════════
        session_label = "london" if 7 <= current_hour < 10 else ("silver_bullet" if in_silver_bullet else "ny_open")
        self.journal.log_entry(
            symbol=symbol,
            direction=direction,
            entry_price=price,
            stop_loss=sl_price,
            take_profit=tp2_price,
            quantity=contracts,
            conviction=conviction,
            regime=regime,
            scenario=scenario,
            silver_bullet=in_silver_bullet,
            session=session_label,
            entry_reason=entry_reason,
            gate_failures=[]
        )
        log.info(f"Trade journal entry logged: {direction.upper()} {symbol} @ {price}")

        if result:
            log.info(f"Signal executed: {direction.upper()} {contracts}x {symbol} | Regime: {regime}")
            self._respond(200, {
                "status": "executed",
                "symbol": symbol,
                "direction": direction,
                "contracts": contracts,
                "conviction": conviction,
                "regime": regime,
                "sta_response": result
            })
        else:
            log.error(f"STA signal delivery failed for {symbol}")
            self._respond(502, {"status": "failed", "reason": "sta_delivery_failed"})

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
    """Check every minute and send close signals at 16:30 ET (20:30 UTC)."""
    sta = SignalTradeAppClient()
    journal = TradeJournal()
    risk_engine = LucidRiskEngine()
    symbols = ["MGC", "MES"]
    while True:
        now = datetime.now(timezone.utc)
        hour_min = now.hour * 60 + now.minute
        target = 20 * 60 + 30  # 20:30 UTC = 16:30 ET
        if target <= hour_min < target + 3:
            log.info("Hard close time reached — closing all positions via STA")
            for sym in symbols:
                sta.close_position(sym)
                # Find the last open trade for this symbol and record exit
                last_trade = journal.get_last_open_trade_by_symbol(sym)
                if last_trade:
                    journal.log_exit(
                        trade_id=last_trade["id"],
                        exit_price=0,
                        exit_reason="hard_close",
                        pnl=0,
                        pnl_pct=0,
                        notes=f"Hard close at {now.isoformat()}"
                    )
                    log.info(f"Hard close logged for {sym} trade_id={last_trade['id']}")
                else:
                    log.info(f"No open trade found for {sym} at hard close")
            time.sleep(120)  # Wait 2 min before checking again
        time.sleep(30)


# ── Main ───────────────────────────────────────
def main():
    """Start the webhook server and hard close scheduler."""
    # Startup balance sync from Tradovate
    try:
        risk_engine = LucidRiskEngine()
        bs = init_balance_sync(risk_engine)
        log.info("Startup balance sync completed")
        # Make sync available to the WebhookHandler class
        WebhookHandler.balance_sync = bs
        WebhookHandler._risk_engine_sync = risk_engine
    except Exception as e:
        log.warning(f"Startup balance sync failed (continuing with state file): {e}")

    # Start hard close scheduler
    t = threading.Thread(target=hard_close_scheduler, daemon=True)
    t.start()

    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), WebhookHandler)
    log.info(f"Aurum Edge Webhook listening on {LISTEN_HOST}:{LISTEN_PORT}")
    log.info(f"STA Webhook URL: {'configured' if STA_WEBHOOK_URL else 'NOT CONFIGURED'}")
    server.serve_forever()


if __name__ == "__main__":
    main()