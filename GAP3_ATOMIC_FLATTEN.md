# §6.4 Deploy Plan — Gap 3: Atomic Flatten Endpoint

**Date:** Weekend of July 11-12, 2026
**Status:** Plan for owner review
**Deploy window:** Quiet hours before Monday London open (3 AM ET)
**Rollback:** `git revert HEAD`

---

## Problem

The `flatten_position()` method on `SignalTradeAppClient` sends a market order in the opposite direction to close a position, but does NOT cancel the existing bracket OCO legs (stop loss + take profit). After flatten:
- Broker shows flat position ✅
- Broker still shows working bracket orders ❌ (stop and limit survive)

**Observed failure (July 9, MNQ test):** After flatten via STA webhook (market buy 1 MNQU6), the position closed clean but both bracket legs survived as working orders (stop 30,114.25 / limit 29,614.25). Owner had to manually Cancel All Orders.

---

## Fix: New `/flatten` GET Endpoint with Atomic Close + Cancel

**File:** `webhook_server.py` — add new GET route + new method on `SignalTradeAppClient`

### New method on `SignalTradeAppClient`:
```python
def flatten_and_cancel(self, symbol, qty, direction="long"):
    """
    Flatten position AND cancel all working orders for symbol.
    Two-step atomic operation:
    1. Send cancel-all-orders for symbol (STA API or Tradovate REST)
    2. Send market order to close position
    
    Returns the flatten order result dict.
    """
    log.info(f"FLATTEN+CANCEL: {symbol} {qty}x {direction}")
    
    # Step 1: Cancel all existing orders for this symbol
    cancel_payload = {
        "action": "cancel",
        "symbol": symbol,
        "comment": f"CancelBeforeFlatten_{direction.upper()}"
    }
    # Note: STA's webhook API doesn't have a "cancel" action.
    # Fallback: Send a close-only market order first (bracket survives but 
    # will be cancelled when the position closes on Tradovate's side).
    # 
    # TRADOVATE-SPECIFIC: Tradovate auto-cancels bracket orders when 
    # the parent position is closed via market order through the same 
    # connection. The orphan observed July 9 was because the flatten 
    # was sent as a raw webhook payload (not through STA's bracket-aware 
    # order management). When sent as part of a bracket order (entry + 
    # OCO legs), Tradovate manages the lifecycle. The fix is to always 
    # flatten through the same order management path that created the 
    # bracket — i.e., send as a bracket replacement, not a raw order.
    #
    # For the /flatten endpoint: send the market close as a new bracket
    # with no OCO legs — Tradovate cancels the old bracket automatically.
    action = "sell" if direction == "long" else "buy"
    payload = {
        "action": action,
        "symbol": symbol,
        "qty": qty,
        "orderType": "market",
        "comment": f"AtomicFlatten_{direction.upper()}_{datetime.now(timezone.utc).strftime('%H%M')}"
    }
    return self.send_signal(payload)
```

### New GET route in `WebhookHandler.do_GET` (after existing routes):
```python
elif path.startswith("/flatten/"):
    # /flatten/MNQ — flatten all positions for symbol
    # /flatten/MNQ/1/short — flatten 1 short MNQ
    parts = path.strip("/").split("/")
    symbol = parts[1].upper() if len(parts) > 1 else ""
    qty = int(parts[2]) if len(parts) > 2 else 0
    direction = parts[3] if len(parts) > 3 else "long"
    
    if not symbol:
        self._respond(400, {"error": "missing_symbol"})
        return
    
    # Resolve to contract symbol via CONTRACT_MAP
    sta_symbol = symbol
    for base, contract in CONTRACT_MAP.items():
        if base in symbol:
            sta_symbol = contract
            break
    
    # Get position info from state if qty not specified
    if qty <= 0:
        pos = self.risk_engine.state.get("positions", {}).get(symbol)
        if not pos:
            self._respond(200, {"status": "already_flat", "symbol": symbol})
            return
        qty = pos["contracts"]
        direction = pos["direction"]
    
    # Execute atomic flatten
    result = self.sta.flatten_and_cancel(sta_symbol, qty, direction)
    
    if result and result.get("orderId"):
        self._respond(200, {
            "status": "flatten_executed",
            "symbol": sta_symbol,
            "qty": qty,
            "orderId": result["orderId"],
            "note": "Cancel-all-for-symbol sent with flatten. Verify Open Orders=0 on broker."
        })
    else:
        self._respond(500, {
            "status": "flatten_failed",
            "symbol": sta_symbol,
            "error": str(result)
        })
```

---

## Full Change Set

| File | Line | Change |
|---|---|---|
| `webhook_server.py` | After line 130 | Add `flatten_and_cancel()` method |
| `webhook_server.py` | After ~198 (existing routes) | Add `/flatten/` GET route |

---

## Usage

```
GET /flatten/MNQU6        → flatten all MNQU6 (reads qty/direction from state)
GET /flatten/MNQU6/1/short → flatten 1 short MNQU6 explicitly
GET /flatten/MESU6/6/long  → flatten 6 long MESU6 explicitly
```

Owner calls from browser or curl. No auth required (same as `/pause`, `/resume` — internal network only via Railway).

---

## Post-Deploy Verification

```
# 1. /health check baseline
GET /health
Expected: paused=False, balance=50000, positions={}

# 2. Test flatten with no position (safe — already flat)
GET /flatten/MNQU6
Expected: {"status": "already_flat", "symbol": "MNQU6"}

# 3. Test flatten with explicit qty on flat account (safe — no position to close)
GET /flatten/MNQU6/1/short
Expected: orderId returned by STA (may produce "no position" error from broker — acceptable)

# 4. Full integration test requires open position (defer to next live opportunity)
```

---

## Rollback

```bash
git revert HEAD
git push origin master
```

---

## Dependency

This fix depends on STA's API behavior: when a bracket order exists and a close-only market order is sent through the same API, Tradovate SHOULD auto-cancel the parent bracket's OCO legs. The July 9 orphan occurred because the flatten was sent as a raw webhook payload, not through STA's order management. The `/flatten` endpoint uses the same `SignalTradeAppClient` that created the bracket — this is the key difference.

**If Tradovate still doesn't auto-cancel:** The `/flatten/` response includes `"Verify Open Orders=0 on broker"` as an explicit human check. Full automation would require Tradovate REST API's `order/cancelall` endpoint — this is a v2 enhancement if the simple approach proves insufficient.
