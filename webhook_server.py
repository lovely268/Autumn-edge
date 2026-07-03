"""
Aurum Edge Webhook Server (Railway)
Receives TradingView alert webhooks, validates signals via the Lucid Risk Engine,
and executes trades via the Tradovate REST API with 3-part bracket order management.
"""
import os
import json
import time
import hmac
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ── Modules ────────────────────────────────────
from tradovate_auth import TradovateAuth
from lucid_risk_engine import LucidRiskEngine

# ── Config ─────────────────────────────────────
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("webhook")

# ── Tradovate API Client ──────────────────────
class TradovateClient:
    """Minimal REST client for placing bracket orders on Tradovate."""

    BASE = "https://live.tradovateapi.com"

    def __init__(self):
        self.auth = TradovateAuth()
        self.account_id = int(os.getenv("TRADOVATE_ACCOUNT_ID", "0"))

    def _ensure_token(self):
        return self.auth.authenticate()

    def find_contract(self, symbol):
        """Resolve 'MGC' or 'MES' to the current active contract ID."""
        token = self._ensure_token()
        if not token:
            return None
        import requests
        # Find the contract from the name pattern
        name = f"{symbol}Z6"  # Dec 2026 — adjust as market rolls
        resp = requests.get(
            f"{self.BASE}/contract/find?name={name}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("id")
        # Fallback: list all contracts for the product
        product_map = {"MGC": 8846978, "MES": 756692}  # Product IDs — verify via API
        prod_id = product_map.get(symbol)
        if not prod_id:
            return None
        resp = requests.get(
            f"{self.BASE}/contract/list?productId={prod_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if resp.status_code == 200:
            contracts = resp.json()
            if contracts:
                # Pick the most recent active contract
                return contracts[-1].get("id")
        return None

    def place_bracket(self, symbol, direction, contracts, entry_price, sl_price, tp_price):
        """
        Place a bracket order: Limit entry + Stop Loss + Take Profit.
        Uses Tradovate's bracketOrder endpoint.
        """
        token = self._ensure_token()
        if not token:
            log.error("Cannot place bracket: no auth token")
            return None

        contract_id = self.find_contract(symbol)
        if not contract_id:
            log.error(f"Cannot find contract for {symbol}")
            return None

        import requests
        bracket_payload = {
            "accountId": self.account_id,
            "action": "Buy" if direction == "long" else "Sell",
            "symbol": symbol,
            "orderQty": contracts,
            "orderType": "Limit",
            "price": entry_price,
            "stopPrice": None,
            "maxShow": contracts,
            "pegDifference": None,
            "timeInForce": "Day",
            "expireTime": None,
            "text": f"AurumEdge {direction} {symbol}",
            "isAutomated": True,
            "linkedOrders": [
                {
                    "action": "Sell" if direction == "long" else "Buy",
                    "orderType": "Stop",
                    "stopPrice": sl_price,
                    "orderQty": contracts,
                    "timeInForce": "Day",
                    "text": "SL"
                },
                {
                    "action": "Sell" if direction == "long" else "Buy",
                    "orderType": "Limit",
                    "price": tp_price,
                    "orderQty": contracts,
                    "timeInForce": "Day",
                    "text": "TP"
                }
            ]
        }

        resp = requests.post(
            f"{self.BASE}/order/placeOrder",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=bracket_payload,
            timeout=15
        )
        if resp.status_code == 200:
            result = resp.json()
            log.info(f"Bracket placed: {result}")
            return result
        else:
            log.error(f"Bracket placement failed: {resp.status_code} {resp.text}")
            return None

    def close_all_positions(self):
        """Flatten all open positions (hard close)."""
        token = self._ensure_token()
        if not token:
            return
        import requests
        resp = requests.get(
            f"{self.BASE}/position/list",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if resp.status_code != 200:
            return
        positions = resp.json()
        for pos in positions:
            if pos.get("netPos", 0) != 0:
                close_qty = abs(pos["netPos"])
                action = "Sell" if pos["netPos"] > 0 else "Buy"
                payload = {
                    "accountId": self.account_id,
                    "action": action,
                    "symbol": pos["symbol"],
                    "orderQty": close_qty,
                    "orderType": "Market",
                    "timeInForce": "Day",
                    "text": "HardClose AurumEdge",
                    "isAutomated": True
                }
                requests.post(
                    f"{self.BASE}/order/placeOrder",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=10
                )
                log.info(f"Hard closed {close_qty} {pos['symbol']}")

    def modify_stop_loss(self, order_id, new_sl_price):
        """Modify stop loss on an existing order to trail or move to BE."""
        token = self._ensure_token()
        if not token:
            return False
        import requests
        payload = {
            "orderId": order_id,
            "stopPrice": new_sl_price,
            "clOrdId": None
        }
        resp = requests.post(
            f"{self.BASE}/order/modifyOrder",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=10
        )
        return resp.status_code == 200


# ── Webhook Handler ────────────────────────────
class WebhookHandler(BaseHTTPRequestHandler):
    tradovate = TradovateClient()
    risk_engine = LucidRiskEngine()

    def do_POST(self):
        path = urlparse(self.path).path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)

        # Healthcheck
        if path == "/health":
            self._respond(200, {"status": "ok", "engine": "Aurum Edge v2.0"})
            return

        # Webhook endpoint
        if path == "/webhook":
            self._handle_webhook(body)
            return

        self._respond(404, {"error": "not_found"})

    def _handle_webhook(self, raw_body):
        """Process incoming TradingView alert."""
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid_json"})
            return

        # Validate signature if secret is set
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

        if not symbol or not direction or price <= 0:
            self._respond(400, {"error": "missing_fields"})
            return

        log.info(f"Signal: {direction.upper()} {symbol} @ {price} (conviction: {conviction}/10)")

        # ── Lucid Risk Gate ──
        gate_result = self.risk_engine.check_gate(symbol, direction, price, conviction)
        if not gate_result["allowed"]:
            log.warning(f"GATE BLOCKED: {gate_result['reason']}")
            self._respond(200, {"status": "blocked", "reason": gate_result["reason"]})
            return

        # ── Kelly Criterion Sizing ──
        contracts = self.risk_engine.calculate_contracts(symbol, direction, price, conviction)
        if contracts <= 0:
            log.warning("Sizing returned 0 contracts — aborting")
            self._respond(200, {"status": "blocked", "reason": "zero_contracts"})
            return

        # ── Determine SL/TP from ATR or signal ──
        sl_target = float(payload.get("sl_target", 0))
        if sl_target > 0:
            sl_dist = abs(price - sl_target)
        else:
            sl_dist = price * 0.005  # fallback 0.5%

        tp_price = price + (sl_dist * 3.0) if direction == "long" else price - (sl_dist * 3.0)

        # ── 3-Part Bracket Placement ──
        part_size = max(1, contracts // 3)
        parts_placed = []
        for i, (label, tp_mod) in enumerate([
            ("TP1 (1.5R)", 1.5),
            ("TP2 (3.0R)", 3.0),
            ("TP3 (Trail)", None)
        ]):
            if i == 2:
                tp = tp_price  # 3.0R as base trail target
            else:
                tp = price + (sl_dist * tp_mod) if direction == "long" else price - (sl_dist * tp_mod)

            qty = part_size if i < 2 else contracts - (2 * part_size)
            if qty <= 0:
                continue

            result = self.tradovate.place_bracket(
                symbol, direction, qty, price,
                price - sl_dist if direction == "long" else price + sl_dist,
                tp
            )
            parts_placed.append({
                "part": label,
                "qty": qty,
                "order_id": result.get("orderId") if result else None,
                "status": "placed" if result else "failed"
            })

        # ── Update risk engine state ──
        self.risk_engine.record_entry(symbol, direction, price, contracts, conviction)

        log.info(f"Executed {direction.upper()} {contracts}x {symbol}: {parts_placed}")
        self._respond(200, {
            "status": "executed",
            "symbol": symbol,
            "direction": direction,
            "contracts": contracts,
            "conviction": conviction,
            "parts": parts_placed,
            "risk_pct": round(gate_result.get("risk_pct", 0) * 100, 2)
        })

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        log.info(f"{self.address_string()} - {fmt % args}")


# ── Hard Close Scheduler (background thread) ──
def hard_close_scheduler():
    """Check every minute and hard close at 16:30 ET (20:30 UTC)."""
    while True:
        now = datetime.now(timezone.utc)
        hour_min = now.hour * 60 + now.minute
        target = 20 * 60 + 30  # 20:30 UTC = 16:30 ET
        if hour_min >= target and hour_min < target + 2:
            log.info("Hard close time reached — flattening all positions")
            client = TradovateClient()
            client.close_all_positions()
        time.sleep(60)


# ── Main ───────────────────────────────────────
if __name__ == "__main__":
    import threading

    # Start hard close scheduler
    t = threading.Thread(target=hard_close_scheduler, daemon=True)
    t.start()

    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), WebhookHandler)
    log.info(f"Aurum Edge Webhook Server listening on {LISTEN_HOST}:{LISTEN_PORT}")
    server.serve_forever()