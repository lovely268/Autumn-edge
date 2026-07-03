"""
Aurum Edge Webhook + Signal Trade App Bridge (Railway)
Receives TradingView alert webhooks → validates via Lucid Risk Engine
→ sends validated signals to Signal Trade App for Tradovate execution.
Also handles health checks, hard close, and evaluation status.
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

# ── Modules ────────────────────────────────────
from lucid_risk_engine import LucidRiskEngine

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

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            status = self.risk_engine.get_status()
            self._respond(200, status)
        elif path == "/":
            self._respond(200, {"service": "Aurum Edge Webhook", "version": "2.0"})
        else:
            self._respond(404, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)

        if path == "/webhook":
            self._handle_webhook(body)
        else:
            self._respond(404, {"error": "not_found"})

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

        symbol = payload.get("symbol", "").replace("=F", "")
        direction = payload.get("direction")
        price = float(payload.get("price", 0))
        conviction = float(payload.get("conviction", 0))
        sl_target = float(payload.get("sl_target", 0))

        if not symbol or not direction or price <= 0:
            self._respond(400, {"error": "missing_fields"})
            return

        log.info(f"Signal: {direction.upper()} {symbol} @ {price} (conviction: {conviction}/10)")

        # ── Lucid Risk Gate ──────────────────────
        gate_result = self.risk_engine.check_gate(symbol, direction, price, conviction)
        if not gate_result["allowed"]:
            log.warning(f"GATE BLOCKED: {gate_result['reason']}")
            self._respond(200, {"status": "blocked", "reason": gate_result["reason"]})
            return

        # ── Kelly Criterion Sizing ───────────────
        contracts = self.risk_engine.calculate_contracts(symbol, direction, price, conviction)
        if contracts <= 0:
            log.warning("Sizing returned 0 contracts — aborting")
            self._respond(200, {"status": "blocked", "reason": "zero_contracts"})
            return

        # ── Determine SL/TP from ATR / signal ────
        if sl_target > 0:
            sl_dist = abs(price - sl_target)
        else:
            sl_dist = price * 0.005  # fallback 0.5%

        tp1_price = price + (sl_dist * 1.5) if direction == "long" else price - (sl_dist * 1.5)
        tp2_price = price + (sl_dist * 3.0) if direction == "long" else price - (sl_dist * 3.0)

        # ── Build STA signal payload ─────────────
        part_size = max(1, contracts // 3)
        remaining = contracts - (2 * part_size)
        sl_price = price - sl_dist if direction == "long" else price + sl_dist

        # STA expects nested bracket object format
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
            "comment": f"AurumEdge_{direction.upper()}"
        }

        # ── Send to Signal Trade App ────────────
        result = self.sta.send_signal(sta_payload)
        self.risk_engine.record_entry(symbol, direction, price, contracts, conviction)

        if result:
            log.info(f"Signal executed: {direction.upper()} {contracts}x {symbol}")
            self._respond(200, {
                "status": "executed",
                "symbol": symbol,
                "direction": direction,
                "contracts": contracts,
                "conviction": conviction,
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
    symbols = ["MGC", "MES"]
    while True:
        now = datetime.now(timezone.utc)
        hour_min = now.hour * 60 + now.minute
        target = 20 * 60 + 30  # 20:30 UTC = 16:30 ET
        if target <= hour_min < target + 3:
            log.info("Hard close time reached — closing all positions via STA")
            for sym in symbols:
                sta.close_position(sym)
            time.sleep(120)  # Wait 2 min before checking again
        time.sleep(30)


# ── Main ───────────────────────────────────────
def main():
    """Start the webhook server and hard close scheduler."""
    # Start hard close scheduler
    t = threading.Thread(target=hard_close_scheduler, daemon=True)
    t.start()

    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), WebhookHandler)
    log.info(f"Aurum Edge Webhook listening on {LISTEN_HOST}:{LISTEN_PORT}")
    log.info(f"STA Webhook URL: {'configured' if STA_WEBHOOK_URL else 'NOT CONFIGURED'}")
    server.serve_forever()


if __name__ == "__main__":
    main()