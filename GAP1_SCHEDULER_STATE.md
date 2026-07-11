# §6.4 Deploy Plan — Gap 1: Scheduler State Divergence

**Date:** Weekend of July 11-12, 2026
**Status:** Plan for owner review
**Deploy window:** Quiet hours before Monday London open (3 AM ET)
**Rollback:** `git revert HEAD`

---

## Problem

The hard close scheduler creates its own local `risk_engine = LucidRiskEngine()` instance at startup (line 553). When the owner calls `/reset_state`, it replaces `WebhookHandler.risk_engine` (the class variable) but NOT the scheduler's local copy. The two diverge.

**Observed failure (July 9):** After /reset_state cleared the state, the scheduler still held MES short 6 in memory from the test sequence. At 16:30 ET it fired flatten orders against a phantom position that only existed in its stale cache.

---

## Fix: Scheduler Reads from Shared Instance

**File:** `webhook_server.py` — lines 553, 566-568

**Diff:**
```python
# OLD (line 553) — remove this entirely:
risk_engine = LucidRiskEngine()

# OLD (lines 566-568) — read from local instance:
pos = risk_engine.state.get("positions", {}).get(sym)
if not pos or pos.get("contracts", 0) <= 0:

# NEW — read from WebhookHandler's shared class variable:
pos = WebhookHandler.risk_engine.state.get("positions", {}).get(sym)
if not pos or pos.get("contracts", 0) <= 0:
```

**Full change set:**
| Line | Change |
|---|---|
| 553 | Delete `risk_engine = LucidRiskEngine()` |
| 566 | `risk_engine.state.get(...)` → `WebhookHandler.risk_engine.state.get(...)` |
| 567-568 | Same reference change on continuation lines |
| ~556 (after while start) | Add SCHEDULER VIEW log line with positions + engine_id |
| ~170-175 (bot_state block) | Add `engine_id: id(self.risk_engine)` to /health response |

**Effect:** The `hard_close_scheduler()` loop runs every 30 seconds and reads `WebhookHandler.risk_engine` — the same instance `/health`, `/webhook`, and `/reset_state` use. When `/reset_state` replaces `WebhookHandler.risk_engine`, the scheduler sees the new state on the next 30-second iteration. No divergence possible.

---

## Code Additions

### 1. SCHEDULER VIEW log line (add after scheduler while-loop start, ~line 556)
```python
# ── SCHEDULER VIEW: log current positions and risk_engine object id ──
pos_summary = {sym: f"{p['direction']} {p['contracts']}x" 
               for sym, p in WebhookHandler.risk_engine.state.get("positions", {}).items()}
log.info(f"SCHEDULER VIEW: positions={pos_summary} "
         f"engine_id={id(WebhookHandler.risk_engine)}")
```

### 2. engine_id in /health (add to bot_state block, ~line 175)
```python
status["bot_state"] = {
    "paused": _bot_paused,
    "pause_reason": _pause_reason,
    "engine_id": id(self.risk_engine),
}
```

---

## Post-Deploy Verification — The engine_id Match Test

**This is the proof the July 9 phantom class is dead.** The fix is proven by showing the scheduler and the webhook handler share the SAME object — not just the same data.

### Step 1: Pre-reset baseline
Pull Railway logs for "SCHEDULER VIEW" — note the `engine_id`:
```
SCHEDULER VIEW: positions={} engine_id=0x7f8a4b1c2d3e
```
Hit /health in your browser — check `bot_state.engine_id`:
```
/health: bot_state.engine_id=0x7f8a4b1c2d3e
```
**Assert: scheduler's engine_id == /health's engine_id** ✅ They share the same object.

### Step 2: Owner runs /reset_state
```
GET /reset_state?token=YOUR_TOKEN
```
Expected: `{"status": "state_reset", ...}`

### Step 3: Post-reset (within 30s — scheduler's next loop)
Pull the next SCHEDULER VIEW log line:
```
SCHEDULER VIEW: positions={} engine_id=0x9b0c2d3e4f5a
```
Hit /health again:
```
/health: bot_state.engine_id=0x9b0c2d3e4f5a
```
**Assert: engine_id changed** (new instance from reset) ✅  
**Assert: scheduler's engine_id == /health's engine_id** (both read the new shared instance) ✅  
**Assert: positions reflect reset** (empty, 0 trades, $50K) ✅

### Evidence to paste:
```
Pre-reset:
  SCHEDULER VIEW: positions={} engine_id=0x7f8a4b1c2d3e
  /health:       bot_state.engine_id=0x7f8a4b1c2d3e  ← MATCH

Post-reset:
  SCHEDULER VIEW: positions={} engine_id=0x9b0c2d3e4f5a
  /health:       bot_state.engine_id=0x9b0c2d3e4f5a  ← MATCH (new shared instance)
  
Both shared. Scheduler divergence is impossible.
```

The SCHEDULER VIEW line ships with the deploy and stays through Monday's close for full visibility. Removed in a quiet-hours follow-up.

---

## Rollback

```bash
git revert HEAD
git push origin master
```

---

## Safety Note

This fix must deploy BEFORE London open on Monday. If the scheduler fires at 11:45 AM ET Friday (or 4:30 PM ET Mon-Thu) with a stale cache, it could flatten positions that don't exist — sending phantom market orders. The `position-check guard` (line 567: `if not pos or pos.get("contracts", 0) <= 0:`) prevents false flats but would also miss real ones if a legitimate position was opened after /reset_state.

The shared-instance approach is the simplest fix with no behavioral change to the flatten logic itself — just a different pointer for state reads.
