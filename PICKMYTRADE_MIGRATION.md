# PickMyTrade Migration Package — Fire-Ready

## Overview
Swap STA → PickMyTrade when STA support is silent past 48h (Wednesday night) OR if STA fix doesn't produce real orderIds.

## Step 1: Owner Actions (5 min)
1. Sign up at https://pickmytrade.io — 5-day free trial, no credit card
2. Connect **Tradovate DEMO8306103** (50K sim) from PickMyTrade dashboard
3. Generate a **webhook URL** from PickMyTrade settings
4. The webhook URL will be something like: `https://api.pickmytrade.io/webhook/xxxxx`
5. Paste the URL into **Railway dashboard** → Environment → set `PMT_WEBHOOK_URL`
6. (Optional) Keep `STA_WEBHOOK_URL` in place as fallback — we can swap by commenting the env var

## Step 2: Code Change — Payload Adapter
In `webhook_server.py`, the `sta_payload` dict (around line 387) needs a minor adjustment:

**Current (STA format):**
```python
sta_payload = {
    "action": sta_action,
    "symbol": "MGC" if "MGC" in symbol else ("MES" if "MES" in symbol else "MNQ"),
    "qty": contracts,
    "orderType": "limit",
    "price": round(price, 2),
    "stopLoss": round(sl_price, 2),
    "takeProfit": round(tp1_price, 2),
}
```

**PickMyTrade format (likely identical — same TradingView alert JSON standard):**
```python
pmt_payload = {
    "action": sta_action,
    "symbol": "MGC" if "MGC" in symbol else ("MES" if "MES" in symbol else "MNQ"),
    "qty": contracts,
    "orderType": "limit",
    "price": round(price, 2),
    "stopLoss": round(sl_price, 2),
    "takeProfit": round(tp1_price, 2),
}
```

**Key difference:** PickMyTrade uses `stopLoss` and `takeProfit` field names (same as STA). If PickMyTrade uses different field names (e.g., `sl`/`tp` or `stop_loss`/`take_profit`), adjust accordingly. The raw curl test in Step 3 will confirm.

### Adapter Implementation
The `send_signal()` method in `SignalTradeAppClient` already reads the webhook URL from an env var. We can:
1. **Option A** — Replace `STA_WEBHOOK_URL` with `PMT_WEBHOOK_URL` in Railway env vars
2. **Option B** — Add a `BRIDGE` env var (`sta` or `pmt`) and conditionally select payload format

Option A is simpler — one env var swap, no code changes needed if payload format matches.

## Step 3: Test Sequence

### 3a. Raw Curl Test (bypass the bot)
```bash
curl -X POST https://api.pickmytrade.io/webhook/xxxxx \
  -H "Content-Type: application/json" \
  -d '{"action":"buy","symbol":"MGC","qty":"1","orderType":"market","stopLoss":4120.0,"takeProfit":4160.0}'
```

**Pass** = response contains a real numeric orderId (e.g., `"orderId": 12345678`)
**Fail** = no orderId or error — check PickMyTrade docs for correct payload format

### 3b. Bot Path Test
1. Set `PMT_WEBHOOK_URL` on Railway (or override `STA_WEBHOOK_URL`)
2. Resume bot: `curl https://autumn-edge-aurum-edge.up.railway.app/resume`
3. Fire standard signal: `curl -X POST https://autumn-edge-aurum-edge.up.railway.app/webhook -H "Content-Type: application/json" -d '{"symbol":"MGC","direction":"long","price":4150.00,"conviction":8.5,"sl_target":4130.00,"entry_reason":"pmt_test","scenario":"sweep_mss_fvg"}'`
4. Check response for `order_id` (real value, not null/undefined)
5. Check `/health` for `last_execution_confirmed: true`
6. Flatten position: send opposite signal
7. Re-pause

### 3c. Hard Close Verification
After a position is opened, verify the hard close scheduler works:
- Uses `flatten_position()` → sends opposite-side market order
- Should produce a real orderId in Tradovate

## Step 4: Gotchas & Risk Register

| Risk | Mitigation |
|------|-----------|
| **Payload format mismatch** | Raw curl test first. If field names differ, adjust adapter in code. |
| **Rate limits** | PickMyTrade says "unlimited trades" — should be fine for 5-10 signals/day |
| **Symbol format** | PickMyTrade uses standard Tradovate symbols (MGC, MES, MNQ) — same as STA |
| **Bracket support** | PickMyTrade supports SL/TP in one payload (OCO brackets). Single TP only (same as STA) |
| **orderId truth-checking** | Our fix (`bool(order_id) and order_id != "undefined"`) works regardless of bridge |
| **Free trial expiry** | 5 days. If longer needed, $50/mo subscription. |
| **Multiple accounts** | PickMyTrade supports multi-account automation — useful for future eval scaling |
| **Bridge swap rollback** | Keep `STA_WEBHOOK_URL` in Railway env vars (commented out). Swap back in 60 seconds. |

## Migration Effort Summary
| Step | Time | Who |
|------|------|-----|
| Sign up + connect Tradovate | 5 min | Owner |
| Get webhook URL | 1 min | Owner |
| Set env var on Railway | 1 min | Owner |
| Verify payload format (raw curl) | 1 min | Bot |
| Fire bot test | 1 min | Bot |
| Unpause for shake-out week | 1 min | Owner says go |
| **Total** | **~10 min** | |

## Files to Modify
- `webhook_server.py` — May need payload field name adjustments (5 min)
- Railway env var — `STA_WEBHOOK_URL` → `PMT_WEBHOOK_URL` (or rename)

## Rollback
If PickMyTrade doesn't work:
1. Set `STA_WEBHOOK_URL` back on Railway
2. Restore any payload format changes
3. Bot is unchanged — same architecture, different URL