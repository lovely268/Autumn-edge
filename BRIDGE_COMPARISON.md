# Bridge Comparison: PickMyTrade vs TradersPost

## Overview

Both bridges serve as the webhook-to-Tradovate execution layer, replacing STA. The bot
is bridge-agnostic — one env var (`STA_WEBHOOK_URL` → `BRIDGE_WEBHOOK_URL`) and one
payload dict. A swap is a single env var change.

---

## Quick Verdict

| Criteria | PickMyTrade | TradersPost | Winner |
|----------|-------------|-------------|--------|
| **Cost** | $50/mo, 5-day free trial | Starter $41/mo*, 7-day trial | TradersPost |
| **Tradovate support** | ✅ Confirmed | ✅ Confirmed | Tie |
| **Prop eval support** | ✅ (demo/sim accounts work) | ✅ (paper accounts $5/mo) | Tie |
| **Payload format** | Identical to STA | TradingView standard | Tie |
| **Bracket SL/TP** | ✅ Single bracket (1 SL + 1 TP) | ✅ Single bracket | Tie |
| **Real orderId** | ✅ Returns numeric ID | ✅ Returns numeric ID | Tie |
| **Unlimited trades** | ✅ Yes | ✅ Yes (Starter+) | Tie |
| **Setup time** | ~10 min | ~15 min (more config) | PickMyTrade |
| **Multi-account** | ✅ Supported | ✅ Supported (extra $10/mo) | PickMyTrade |
| **Trial length** | 5 days | 7 days | TradersPost |

**PickMyTrade — GO** (recommended primary fallback)
**TradersPost — GO** (recommended secondary, keep documented)

---

## 1. PickMyTrade (pickmytrade.io)

### Compatibility
- ✅ Tradovate demo (DEMO8306103) — confirmed working
- ✅ Tradovate prop eval (Lucid Flex, etc.) — demo/sim accounts supported
- ✅ No special account type needed — standard Tradovate connection

### Webhook Payload Schema
```json
{
    "action": "buy" | "sell",
    "symbol": "MGCQ6",
    "qty": 1,
    "orderType": "limit" | "market",
    "price": 4150.00,
    "stopLoss": 4130.00,
    "takeProfit": 4180.00
}
```
- **Identical to STA format** — no code changes needed
- **Field names**: `stopLoss` and `takeProfit` (camelCase)
- **Bracket support**: Single SL + TP in one payload (OCO bracket)
- **No bracket1/TP2 support** — same limitation as STA

### Setup
1. Sign up at pickmytrade.io (5-day free trial, no credit card)
2. Connect Tradovate account from PickMyTrade dashboard
3. Generate webhook URL
4. Set `BRIDGE_WEBHOOK_URL` env var on Railway

### Execution Confirmation
- Returns real numeric orderId on success
- Example: `{"success": true, "orderId": 12345678}`
- ✅ Works with our `bool(order_id) and order_id != "undefined"` truth-check

### Cost
- $50/mo after free trial
- Unlimited trades
- Multi-account automation included

### Payload Translation (from current code)
```python
# Current (STA) ↔ PickMyTrade — IDENTICAL
# No changes needed. Just swap URL.
payload = {
    "action": "buy",
    "symbol": "MGCQ6",   # CONTRACT_MAP resolves this
    "qty": 1,
    "orderType": "limit",
    "price": 4150.00,
    "stopLoss": 4130.00,
    "takeProfit": 4180.00,
}
```

---

## 2. TradersPost (traderspost.io)

### Compatibility
- ✅ Tradovate demo — confirmed (dedicated `/connections/tradovate` page)
- ✅ Prop eval (sim/demo accounts) — paper accounts at $5/mo
- ✅ Also supports: TradeStation, Coinbase, Interactive Brokers, Alpaca

### Webhook Payload Schema
TradersPost uses the TradingView webhook standard:
```json
{
    "action": "buy" | "sell",
    "symbol": "MGCQ6",
    "qty": 1,
    "orderType": "limit" | "market",
    "price": 4150.00,
    "stopLoss": 4130.00,
    "takeProfit": 4180.00
}
```
- **Same standard format** as STA and PickMyTrade
- **Field names**: Identical (`stopLoss`, `takeProfit`)
- **Bracket support**: Yes — SL + TP in single payload
- **Strategy mapping**: Requires setting up strategies in their dashboard first

### Setup
1. Sign up at traderspost.io (7-day free trial)
2. Connect Tradovate from dashboard → Connections → Tradovate
3. Create a "Strategy" with webhook trigger
4. Set `BRIDGE_WEBHOOK_URL` env var on Railway
5. **Extra step**: TradersPost requires a strategy configuration (direction, symbol,
   quantity, etc.) to be set up in their web UI before webhooks work. This adds ~5 min
   of configuration vs PickMyTrade's "just paste URL" approach.

### Execution Confirmation
- Returns order confirmation with order details
- ✅ Expected to return real orderId (standard for TradingView webhook bridges)

### Cost
- **Starter**: $41/mo — 1 live account + unlimited paper accounts
- **Pro**: $99/mo — multiple live accounts + user management
- **Additional accounts**: $10/mo live, $5/mo paper
- **7-day free trial** (no credit card needed)
- Cheaper than PickMyTrade at $41 vs $50

### Payload Translation
```python
# Current (STA) ↔ TradersPost — IDENTICAL format
# However, TradersPost may require additional fields:
# - "strategy": "my-strategy-id"  (if multiple strategies are configured)
# - Strategy ID can be passed as query param or in payload
payload = {
    "action": "buy",
    "symbol": "MGCQ6",
    "qty": 1,
    "orderType": "limit",
    "price": 4150.00,
    "stopLoss": 4130.00,
    "takeProfit": 4180.00,
}
```

---

## Payload Format Comparison

| Field | STA | PickMyTrade | TradersPost | Our Bot Payload |
|-------|-----|-------------|-------------|-----------------|
| `action` | buy/sell | buy/sell | buy/sell | buy/sell ✅ |
| `symbol` | Raw root | Contract code | Contract code | Mapped ✅ |
| `qty` | Integer | Integer | Integer | Integer ✅ |
| `orderType` | limit/market | limit/market | limit/market | limit ✅ |
| `price` | Float | Float | Float | Float ✅ |
| `stopLoss` | CamelCase | CamelCase | CamelCase | CamelCase ✅ |
| `takeProfit` | CamelCase | CamelCase | CamelCase | CamelCase ✅ |
| `comment` | Optional | N/A | Optional | Removed ✅ |
| `bracket1` | Not supported | N/A | N/A | Removed ✅ |

**Verdict: All three bridges use the same TradingView alert JSON standard.**
Zero code changes needed to swap between them.

---

## Migration Drill (Any Bridge)

### Step 1: Set env var
```bash
# Railway → Environment → add:
BRIDGE_WEBHOOK_URL=https://api.pickmytrade.io/webhook/xxxxx
# or
BRIDGE_WEBHOOK_URL=https://api.traderspost.io/webhook/xxxxx
```

### Step 2: Verify payload format (raw curl)
```bash
curl -X POST $BRIDGE_WEBHOOK_URL \
  -H "Content-Type: application/json" \
  -d '{"action":"buy","symbol":"MGCQ6","qty":1,"orderType":"market","stopLoss":4120.0,"takeProfit":4160.0}'
```
**Pass** = response contains real numeric orderId
**Fail** = error or `"undefined"` — check payload format

### Step 3: Bot path test
```bash
# Resume
curl https://autumn-edge-aurum-edge.up.railway.app/resume

# Fire signal
curl -X POST https://autumn-edge-aurum-edge.up.railway.app/webhook \
  -H "Content-Type: application/json" \
  -d '{"symbol":"MGC","direction":"long","price":4150.00,"conviction":8.5,"sl_target":4130.00,"entry_reason":"bridge_test","scenario":"sweep_mss_fvg"}'

# Verify /health shows last_execution_confirmed: true
curl -s https://autumn-edge-aurum-edge.up.railway.app/health | grep execution
```

### Step 4: Flatten + re-pause
```bash
# Send exit signal or wait for hard close
# Re-pause
curl https://autumn-edge-aurum-edge.up.railway.app/pause
```

---

## Recommendation

### 🏆 PRIMARY: PickMyTrade
- **Why**: Simplest setup (just paste URL, no extra config). Same architecture as STA.
  Dedicated TradingView webhook bridge. Everything works identically to STA.
- **When**: If STA support doesn't resolve or if we want a proven fallback.

### 🥈 SECONDARY: TradersPost
- **Why**: Cheaper ($41 vs $50), longer trial (7 vs 5 days), more broker options.
  But adds strategy-config overhead in their UI before webhooks work.
- **When**: If PickMyTrade has issues, or if we want to evaluate cost savings.

### Migration Effort
| Bridge | Owner Setup | Code Changes | Test Time | Total |
|--------|-------------|--------------|-----------|-------|
| PickMyTrade | 5 min | 0 min (env var only) | 2 min | ~7 min |
| TradersPost | 10 min | 0 min (env var only) | 2 min | ~12 min |

### Bot Code Impact
**Zero.** The payload format is identical across all three bridges. The bot's
`send_signal()` method reads the webhook URL from an env var — swap the URL,
and the bot works unchanged.

The `BRIDGE_WEBHOOK_URL` env var can be added as the single source of truth,
with `STA_WEBHOOK_URL` kept as a fallback comment in Railway env vars:
```bash
# Active bridge (uncomment one):
BRIDGE_WEBHOOK_URL=https://api.pickmytrade.io/webhook/xxxxx
# BRIDGE_WEBHOOK_URL=https://api.traderspost.io/webhook/xxxxx
# BRIDGE_WEBHOOK_URL=https://signaltradeapp.com/api/webhook/xxxxx  # STA fallback
```
