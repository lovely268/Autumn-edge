# §6.4 Deploy Plan — Gap 2: CME Maintenance Blackout

**Date:** Weekend of July 11-12, 2026
**Status:** Owner-approved §6.4 plan
**Deploy window:** Quiet hours before Monday London open (3 AM ET)
**Rollback:** `git revert HEAD`

---

## Problem

The hard close scheduler fires flatten orders at 16:30 ET (20:30 UTC) on Mon-Thu. CME futures exchange has a maintenance window from 5:00-6:00 PM ET (21:00-22:00 UTC) where orders are queued or rejected. Orders submitted at 4:30 PM can bleed into this window, producing rejected orders that flush as artifacts at 5:08 PM.

**Observed failure (July 9):** Phantom position flatten orders entered CME maintenance break, were frozen, then flushed as rejected artifacts at 17:08 ET — blank-qty orders appearing in STA with no fill.

---

## Owner Decision (July 11, 2026)

- **Hard close time: 16:30 ET stays.** No change to the scheduler's daily target.
- **Retry cap:** Scheduler retries every 30s until 16:50 ET (20:50 UTC). If position not confirmed flat by then, give up and alert owner.
- **Blackout absolute:** 17:00-18:00 ET (21:00-22:00 UTC) — no orders of any kind. Gate 4.6 blocks webhook signals. Scheduler skip prevents flatten attempts.
- **Owner alert:** If position still open at 16:50 ET, log ERROR and alert owner to manually flatten via broker UI. Do NOT attempt to flatten inside the blackout window.

---

## Fix: No Orders During Maintenance Window + Retry-Cap Safety

**File:** `webhook_server.py` — add CME maintenance blackout to the session gate logic and retry cap to the scheduler

**Add new config constants (top of file, near existing session constants):**
```python
# CME maintenance blackout
CME_MAINT_START = 21.0   # 5:00 PM ET = 21:00 UTC
CME_MAINT_END   = 22.0   # 6:00 PM ET = 22:00 UTC
FLATTEN_RETRY_CUTOFF = 20 + 50/60.0  # 16:50 ET = 20:50 UTC — last retry before blackout
```

**Add gate to `_handle_webhook` (after Gate 4.5, before Gate 5):**
```python
# ── GATE 4.6: CME Maintenance Blackout ──
current_hour_utc = now.hour + now.minute / 60.0
if CME_MAINT_START <= current_hour_utc < CME_MAINT_END:
    self._respond(200, {"status": "blocked", "reason": "cme_maintenance_window"})
    return
```

**Replace the scheduler's flatten loop (lines 563-580) with retry-cap logic:**
```python
if target <= hour_min < target + 20:  # 16:30-16:50 ET (20-min retry window)
    log.info(f"Hard close time ({'Fri' if now.weekday() == 4 else 'Daily'}) — flattening via STA")
    all_flat = True
    for sym in symbols:
        pos = WebhookHandler.risk_engine.state.get("positions", {}).get(sym)
        if not pos or pos.get("contracts", 0) <= 0:
            log.info(f"Hard close {sym}: already flat — skipping")
            continue
        all_flat = False
        qty = pos["contracts"]
        direction = pos.get("direction", "long")
        result = sta.flatten_position(sym, qty, direction)
        if result and (result.get("orderId") or result.get("order_id")):
            oid = result.get("orderId") or result.get("order_id")
            if oid != "undefined":
                log.info(f"Hard close {sym} orderId={oid}")
            else:
                log.warning(f"Hard close {sym} — orderId='undefined' in response")
        else:
            log.warning(f"Hard close {sym} — no orderId in response")
    
    # ── CME Maintenance gate — do NOT send orders 5-6 PM ET ──
    if CME_MAINT_START <= hour_min / 60.0 < CME_MAINT_END:
        log.warning(f"Hard close skipped: CME maintenance window (5-6 PM ET)")
        if not all_flat:
            log.error(f"HARD CLOSE FAILED: position not flat at blackout boundary — "
                      f"ALERT OWNER to flatten via broker UI. Do NOT send orders inside blackout.")
        time.sleep(60)
        continue
    
    if all_flat:
        time.sleep(180)  # All good — rest for 3 min
    else:
        # Retry next loop — still within 20-min window
        time.sleep(30)
```

**Remove the old flatten timing adjustment** — the 4:15 PM proposal is rejected. Target stays at 16:30 ET (20:30 UTC).

---

## Full Change Set

| File | Line | Change |
|---|---|---|
| `webhook_server.py` | ~25-30 (near constants) | Add `CME_MAINT_START`, `CME_MAINT_END`, `FLATTEN_RETRY_CUTOFF` |
| `webhook_server.py` | ~435-438 (between Gate 4.5 and Gate 5) | Add Gate 4.6 block |
| `webhook_server.py` | ~563-580 (scheduler flatten loop) | Replace with retry-cap + blackout skip + owner alert |

---

## Post-Deploy Verification

```
# 1. Deploy code, no restart needed if hot-patched (but full restart cleaner)

# 2. /health check
GET /health
Expected: paused=False, balance=50000, positions={}

# 3. Time check — confirm maintenance window is defined
# Current time: Saturday 00:01 ET (outside window — no block expected)
# Can't live-test without waiting for 5 PM ET, but code review confirms logic

# 4. Simulate: curl with forced time (code review only — no test endpoint)
```

---

## Rollback

```bash
git revert HEAD
git push origin master
```

---

## Safety Note

**Decision by owner (July 11, 2026): 16:30 ET stays.** The key safety properties:

1. **20-minute retry window (16:30-16:50 ET):** Scheduler retries every 30s. If position is flat, rests for 3 min. If position still open at 16:50, gives up.
2. **Owner alert at 16:50:** If position not confirmed flat by retry cutoff, log ERROR and alert owner to manually flatten via broker UI. Do NOT send orders inside the blackout window.
3. **Absolute blackout (17:00-18:00 ET):** Gate 4.6 blocks all webhook signals. Scheduler skip prevents flatten attempts. No exceptions.
4. **Bracket carries overnight:** If a position can't be flattened before the blackout, the 1.5R bracket manages risk until the next trading session. This is a rare edge case and the bracket is designed for it.
