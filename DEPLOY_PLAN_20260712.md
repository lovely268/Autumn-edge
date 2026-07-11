# §6.4 Deploy Plan — Balance Sync Cleanup (Weekend Quiet Hours)

**Date:** Weekend of July 11-12, 2026
**Status:** Owner-approved §6.4 plan
**Deploy window:** Markets closed (any time)
**Rollback:** `git revert <sha>` on failure
**Scope:** 5 fixes only — balance sync logging, counters, cooldown, and log levels. No scheduler changes (Gap 1 ships as its own plan).

---

## Fix 1: Cap Consecutive Failures Counter

**File:** `tradovate_balance_sync.py` — line 319

**Problem:** `consecutive_sync_failures` increments without cap. Every `/health` call invokes `periodic_reconcile()` → `_record_failure()` → `+= 1`. Counter blows past `MAX_CONSECUTIVE_FAILURES=3` to 5, 10, etc. Log shows `[5/3]` confusingly.

**Diff:**
```python
# OLD (line 319):
self.state["consecutive_sync_failures"] += 1

# NEW:
self.state["consecutive_sync_failures"] = min(
    self.state["consecutive_sync_failures"] + 1,
    MAX_CONSECUTIVE_FAILURES
)
```

**Effect:** Counter caps at 3. Log shows `[3/3]` once threshold reached, never `[5/3]`.

---

## Fix 2: Stop /health from Triggering Sync Every Call + Startup Seed

**File:** `webhook_server.py` — lines 181-187, and `tradovate_balance_sync.py`

**Problem:** `periodic_reconcile()` is called on every `/health` GET, which fires a live Tradovate API call AND increments the failure counter. Every health check = one more failure logged.

**Startup-seed requirement:** The boot-time `startup_sync()` call (in `init_balance_sync`) already calls `_record_success()` on success, which sets `last_sync_time_utc`. This seeds the cooldown timer. Post-deploy, the first `/health` check immediately after boot sees the startup sync's timestamp and respects the 30-min cooldown from boot — no extra live call. If startup sync failed (no timestamp set), the first `/health` will attempt reconcile immediately (correct behavior — try again on failure).

**Diff:**
```python
# OLD (lines 181-187):
try:
    bs = get_balance_sync()
    status["balance_sync"] = bs.get_sync_info()
    if bs.risk_engine:
        status["balance_sync"]["last_reconcile"] = bs.periodic_reconcile()
except Exception as e:
    status["balance_sync"] = {"error": str(e), "synced": False}

# NEW:
try:
    bs = get_balance_sync()
    status["balance_sync"] = bs.get_sync_info()
    # Only reconcile if cooldown elapsed (1800s) or never synced
    if bs.risk_engine and bs._should_reconcile():
        status["balance_sync"]["last_reconcile"] = bs.periodic_reconcile()
    else:
        status["balance_sync"]["last_reconcile"] = {
            "synced": False,
            "reason": "cooldown",
            "consecutive_failures": bs.state["consecutive_sync_failures"],
            "using": "state_file",
            "state_balance": round(bs.risk_engine.state["balance"], 2),
        }
except Exception as e:
    status["balance_sync"] = {"error": str(e), "synced": False}
```

**Add method to `tradovate_balance_sync.py` (after `_record_failure`):**
```python
def _should_reconcile(self):
    """Return True if enough time has passed since last sync attempt."""
    last = self.state.get("last_sync_time_utc")
    if not last:
        return True
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
        return elapsed >= SYNC_COOLDOWN_SECONDS
    except Exception:
        return True
```

**Effect:** `/health` no longer triggers a live API call on every poll. Cooldown respects the 30-minute `SYNC_COOLDOWN_SECONDS`.

---

## Fix 3: Remove Duplicate ERROR Log from `periodic_reconcile`

**File:** `tradovate_balance_sync.py` — lines 250-252

**Problem:** `periodic_reconcile()` calls `_record_failure()` on failure, AND both log the same ERROR. The ERROR fires twice per failure once past threshold.

**Diff:**
```python
# OLD (lines 248-253):
if self.state["consecutive_sync_failures"] >= MAX_CONSECUTIVE_FAILURES:
    self.state["sync_blocked"] = True
    log.error(f"BALANCE SYNC: {MAX_CONSECUTIVE_FAILURES} consecutive failures — "
              f"blocking NEW entries until sync recovers")
    result["sync_blocked"] = True
    self._save_state()

# NEW:
if self.state["consecutive_sync_failures"] >= MAX_CONSECUTIVE_FAILURES:
    self.state["sync_blocked"] = True
    # Note: ERROR-level log is in _record_failure() — single source
    result["sync_blocked"] = True
    self._save_state()
```

**Effect:** Only `_record_failure()` fires the ERROR. No duplicate.

---

## Fix 4: Misleading "blocking" Log — Demo vs Live Level

**File:** `tradovate_balance_sync.py` — lines 324-325 (in `_record_failure`)

**Problem:** The ERROR says "blocking NEW entries" but in demo mode Gate 4.5 is entirely skipped — nothing is blocked. An ERROR that means nothing trains everyone to ignore ERRORs.

**Diff:**
```python
# OLD (lines 322-326):
if self.state["consecutive_sync_failures"] >= MAX_CONSECUTIVE_FAILURES:
    self.state["sync_blocked"] = True
    log.error(f"BALANCE SYNC: {self.state['consecutive_sync_failures']} consecutive failures — "
              f"blocking NEW entries until sync recovers")

# NEW:
if self.state["consecutive_sync_failures"] >= MAX_CONSECUTIVE_FAILURES:
    self.state["sync_blocked"] = True
    env = os.getenv("TRADOVATE_ENV", "demo").lower()
    if env == "live":
        log.error(f"BALANCE SYNC (LIVE): {self.state['consecutive_sync_failures']} consecutive failures — "
                  f"blocking NEW entries until sync recovers")
    else:
        log.warning(f"BALANCE SYNC (DEMO): {self.state['consecutive_sync_failures']} consecutive failures — "
                    f"sync_blocked flag set (no effect in demo mode)")
```

**Effect:** In demo → WARNING, honest about "no effect." In live → ERROR, means something real.

---

## Fix 5: Tradovate 404 — Pre-Live URL Note

**Files:** `tradovate_auth.py` line 11, `tradovate_balance_sync.py` line 38

**Problem:** `https://demo.tradovateapi.com` returns 404 on auth endpoints. The correct Tradovate REST API base URL needs to be verified before live activation.

**No code change this deploy** — documented here for pre-live readiness:

```python
# Current (both files):
TRADOVATE_API_URL = f"https://{'demo' if _env == 'demo' else 'live'}.tradovateapi.com"

# Needs investigation — possible correct URL:
# TRADOVATE_API_URL = f"https://{'demo' if _env == 'demo' else 'live'}.tradovateapi.com/v1"
# OR: other host format entirely
```

**Action required before live:** Verify correct Tradovate REST API base URL by testing auth endpoint directly. Update both files in a pre-live §6.4 deploy.

---

## Deploy Order

| Step | Action | Verification |
|---|---|---|
| 1 | Branch from master: `git checkout -b fix/balance-sync-cleanup` | Branch created |
| 2 | Apply Fix 1 (cap counter) + Fix 4 (demo/live log level) in `tradovate_balance_sync.py` | Lines match diff |
| 3 | Apply Fix 3 (remove duplicate log) in `tradovate_balance_sync.py` | Lines match diff |
| 4 | Apply Fix 2 (cooldown + `_should_reconcile()`) in both files | Method added, `/health` path updated |
| 5 | `git add -A && git commit -m "fix: balance sync counters, cooldown+seed, log levels, dedup"` | Clean commit |
| 6 | `git push origin fix/balance-sync-cleanup` | Push succeeds |
| 7 | Open PR → merge to master | PR merged |
| 8 | Railway auto-deploys master (or manual deploy) | New build starts |
| 9 | **Post-deploy verification** (see below) | All checks pass |

---

## Post-Deploy Verification

```python
# 1. Health check — bot_state, balance, positions
GET /health
Expected: paused=False, balance=50000, positions={}

# 2. Counter behavior — two consecutive /health calls
GET /health  # first call
Expected: consecutive_failures <= 3, single WARNING log (not ERROR in demo)

# 3. Second /health call — counter should NOT increment
GET /health  # second call within 30 min
Expected: same consecutive_failures value as first call (cooldown active)

# 4. Single log line per failure
Expected: grep for "BALANCE SYNC" shows one line per failure, not two

# 5. Log level check
Expected: in demo, log shows WARNING "BALANCE SYNC (DEMO)" not ERROR
```

---

## Rollback

```bash
# If any verification fails:
git revert HEAD
git push origin master
# Railway redeploys automatically
```

---

## Plan Hash

```
RULES.md §6.4 — Deploy plan approved by owner July 12, 2026
Plan file: DEPLOY_PLAN_20260712.md
```