"""
Tradovate Live Balance Sync
Queries Tradovate's cash balance endpoint to keep the risk engine's
balance in sync with the actual brokerage account.
v1.0 — Startup sync, post-exit reconcile, failure handling.
"""
import os
import json
import time
import logging
import requests
from datetime import datetime, timezone

log = logging.getLogger("balance_sync")

# ── Constants ──
SYNC_WARN_THRESHOLD = 50          # $50 delta triggers warning
MAX_CONSECUTIVE_FAILURES = 3      # Block new entries after this many failures
SYNC_COOLDOWN_SECONDS = 1800      # 30 min between periodic syncs

# State file for sync tracking (separate from risk engine state)
SYNC_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "balance_sync_state.json")


class BalanceSync:
    """
    Manages live balance synchronization with Tradovate.
    Tracks consecutive failures, sync timestamps, and provides
    methods for startup sync, post-exit reconcile, and periodic sync.
    """

    def __init__(self, auth_module=None, risk_engine=None):
        self.auth = auth_module
        self.risk_engine = risk_engine
        self.state = self._load_state()
        # Determine API base from env
        env = os.getenv("TRADOVATE_ENV", "demo").lower()
        self.api_url = f"https://{'demo' if env == 'demo' else 'live'}.tradovateapi.com"
        # Account ID from env or discover on first sync
        self.account_id = os.getenv("TRADOVATE_ACCOUNT_ID", "")

    # ── Persistence ──
    def _load_state(self):
        defaults = {
            "consecutive_sync_failures": 0,
            "last_sync_time_utc": None,
            "last_live_balance": None,
            "sync_blocked": False,      # True if 3+ consecutive failures
            "total_syncs": 0,
            "successful_syncs": 0,
            "failed_syncs": 0,
        }
        if os.path.exists(SYNC_STATE_PATH):
            try:
                with open(SYNC_STATE_PATH) as f:
                    return {**defaults, **json.load(f)}
            except (json.JSONDecodeError, OSError):
                pass
        return defaults

    def _save_state(self):
        try:
            with open(SYNC_STATE_PATH, "w") as f:
                json.dump(self.state, f, indent=2)
        except OSError as e:
            log.error(f"Failed to save sync state: {e}")

    # ── API Helpers ──
    def _get_token(self):
        """Get a valid access token from the auth module."""
        if self.auth:
            return self.auth.authenticate()
        # Fallback: try importing directly
        try:
            from tradovate_auth import TradovateAuth
            self.auth = TradovateAuth()
            return self.auth.authenticate()
        except Exception as e:
            log.error(f"Auth init failed: {e}")
            return None

    def _get_account_id(self):
        """Get the trading account ID. Tries env var first, then API discovery."""
        if self.account_id:
            return self.account_id

        token = self._get_token()
        if not token:
            return None

        try:
            resp = requests.get(
                f"{self.api_url}/account/list",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15
            )
            if resp.status_code == 200:
                accounts = resp.json()
                if accounts:
                    # Prefer the first active trading account
                    for acc in accounts:
                        if acc.get("active", False):
                            self.account_id = str(acc["id"])
                            log.info(f"Discovered account: id={self.account_id} name={acc.get('name','')}")
                            return self.account_id
                    self.account_id = str(accounts[0]["id"])
                    return self.account_id
            log.error(f"Account list failed: {resp.status_code} {resp.text[:200]}")
            return None
        except Exception as e:
            log.error(f"Account list error: {e}")
            return None

    def get_live_balance(self):
        """
        Query Tradovate's cash balance endpoint.
        Returns (balance_float, error_string_or_None).
        """
        token = self._get_token()
        if not token:
            return None, "auth_failed"

        account_id = self._get_account_id()
        if not account_id:
            return None, "no_account_id"

        try:
            resp = requests.post(
                f"{self.api_url}/cashbalance/getcashbalancesnapshot",
                json={"accountId": int(account_id)},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                # The response has an "amount" field with the cash balance
                balance = float(data.get("amount", 0))
                return balance, None
            else:
                err_msg = f"{resp.status_code}: {resp.text[:200]}"
                return None, err_msg
        except requests.Timeout:
            return None, "timeout"
        except requests.ConnectionError:
            return None, "connection_error"
        except Exception as e:
            return None, str(e)

    # ── Sync Operations ──

    def startup_sync(self):
        """
        Called ONCE on bot startup.
        Overwrites the risk engine state balance with the live Tradovate value.
        Logs the delta.
        Returns True if sync succeeded, False otherwise.
        """
        if not self.risk_engine:
            log.warning("startup_sync: no risk_engine provided")
            return False

        state_balance = self.risk_engine.state["balance"]
        live_balance, error = self.get_live_balance()

        if live_balance is None:
            log.warning(f"BALANCE SYNC (startup): FAILED — {error}")
            log.warning("Continuing with state file balance — no live correction applied")
            self._record_failure()
            return False

        delta = live_balance - state_balance
        self.risk_engine.state["balance"] = live_balance
        # Also update peak_balance and daily_high_watermark if live is higher
        if live_balance > self.risk_engine.state["peak_balance"]:
            self.risk_engine.state["peak_balance"] = live_balance
        if live_balance > self.risk_engine.state["daily_high_watermark"]:
            self.risk_engine.state["daily_high_watermark"] = live_balance

        self._record_success(live_balance)
        log.info(f"BALANCE SYNC (startup): state=${state_balance:.2f}, "
                 f"tradovate=${live_balance:.2f}, delta=${delta:+.2f} → using tradovate")
        self.risk_engine._save_state()
        return True

    def post_exit_reconcile(self):
        """
        Called AFTER every record_exit().
        Queries live balance and reconciles if delta > $50.
        Does NOT throw — logs warnings and continues.
        """
        if not self.risk_engine:
            return

        state_balance = self.risk_engine.state["balance"]
        live_balance, error = self.get_live_balance()

        if live_balance is None:
            log.warning(f"BALANCE SYNC (post-exit): FAILED — {error}")
            self._record_failure()
            return

        delta = live_balance - state_balance
        warn = abs(delta) > SYNC_WARN_THRESHOLD

        if warn:
            log.warning(f"BALANCE SYNC (post-exit): state=${state_balance:.2f}, "
                        f"tradovate=${live_balance:.2f}, delta=${delta:+.2f} [WARN >$50] — adopting live")
            self.risk_engine.state["balance"] = live_balance
            if live_balance > self.risk_engine.state["peak_balance"]:
                self.risk_engine.state["peak_balance"] = live_balance
            if live_balance > self.risk_engine.state["daily_high_watermark"]:
                self.risk_engine.state["daily_high_watermark"] = live_balance
            self.risk_engine._save_state()
        else:
            log.info(f"BALANCE SYNC (post-exit): state=${state_balance:.2f}, "
                     f"tradovate=${live_balance:.2f}, delta=${delta:+.2f} [OK]")

        self._record_success(live_balance)

    def periodic_reconcile(self):
        """
        Called periodically (every ~30 min) during trading hours.
        Same as startup_sync but respects cooldown and tracks consecutive failures.
        Returns the live balance dict (or error dict) for health endpoint.
        """
        if not self.risk_engine:
            return {"synced": False, "error": "no_risk_engine"}

        state_balance = self.risk_engine.state["balance"]
        live_balance, error = self.get_live_balance()

        if live_balance is None:
            self._record_failure()
            result = {
                "synced": False,
                "error": error,
                "consecutive_failures": self.state["consecutive_sync_failures"],
                "using": "state_file",
                "state_balance": round(state_balance, 2),
            }
            log.warning(f"BALANCE SYNC (periodic): FAILED ({error}) "
                        f"[{self.state['consecutive_sync_failures']}/{MAX_CONSECUTIVE_FAILURES}]")

            # Block new entries after 3 consecutive failures
            if self.state["consecutive_sync_failures"] >= MAX_CONSECUTIVE_FAILURES:
                self.state["sync_blocked"] = True
                log.error(f"BALANCE SYNC: {MAX_CONSECUTIVE_FAILURES} consecutive failures — "
                          f"blocking NEW entries until sync recovers")
                result["sync_blocked"] = True
                self._save_state()

            return result

        delta = live_balance - state_balance
        warn = abs(delta) > SYNC_WARN_THRESHOLD

        if warn:
            self.risk_engine.state["balance"] = live_balance
            if live_balance > self.risk_engine.state["peak_balance"]:
                self.risk_engine.state["peak_balance"] = live_balance
            if live_balance > self.risk_engine.state["daily_high_watermark"]:
                self.risk_engine.state["daily_high_watermark"] = live_balance
            self.risk_engine._save_state()

        self._record_success(live_balance)
        log.info(f"BALANCE SYNC (periodic): state=${state_balance:.2f}, "
                 f"tradovate=${live_balance:.2f}, delta=${delta:+.2f}"
                 f"{' [WARN >$50]' if warn else ' [OK]'}")

        return {
            "synced": True,
            "state_balance": round(state_balance, 2),
            "live_balance": round(live_balance, 2),
            "delta": round(delta, 2),
            "delta_warn": warn,
            "consecutive_failures": self.state["consecutive_sync_failures"],
            "sync_blocked": self.state.get("sync_blocked", False),
            "total_syncs": self.state["total_syncs"],
        }

    def reset_sync_block(self):
        """Call this after a successful sync to unblock new entries."""
        if self.state.get("sync_blocked"):
            self.state["sync_blocked"] = False
            log.info("BALANCE SYNC: Block lifted — sync recovered")
            self._save_state()

    def is_sync_blocked(self):
        """Returns True if sync is blocked (3+ consecutive failures)."""
        return self.state.get("sync_blocked", False)

    def get_sync_info(self):
        """Return sync state summary for health endpoint."""
        return {
            "consecutive_failures": self.state["consecutive_sync_failures"],
            "last_sync_time": self.state.get("last_sync_time_utc"),
            "last_live_balance": self.state.get("last_live_balance"),
            "sync_blocked": self.state.get("sync_blocked", False),
            "total_syncs": self.state["total_syncs"],
            "successful_syncs": self.state["successful_syncs"],
            "failed_syncs": self.state["failed_syncs"],
        }

    # ── Internal Tracking ──

    def _record_success(self, balance):
        self.state["consecutive_sync_failures"] = 0
        self.state["last_sync_time_utc"] = datetime.now(timezone.utc).isoformat()
        self.state["last_live_balance"] = round(balance, 2)
        self.state["total_syncs"] += 1
        self.state["successful_syncs"] += 1
        self.state["sync_blocked"] = False
        self._save_state()

    def _record_failure(self):
        self.state["consecutive_sync_failures"] += 1
        self.state["total_syncs"] += 1
        self.state["failed_syncs"] += 1
        if self.state["consecutive_sync_failures"] >= MAX_CONSECUTIVE_FAILURES:
            self.state["sync_blocked"] = True
            log.error(f"BALANCE SYNC: {self.state['consecutive_sync_failures']} consecutive failures — "
                      f"blocking NEW entries until sync recovers")
        self._save_state()


# ── Module-level singleton ──
_sync_instance = None


def get_balance_sync(auth=None, risk_engine=None):
    """Get or create the shared BalanceSync singleton."""
    global _sync_instance
    if _sync_instance is None:
        from tradovate_auth import TradovateAuth
        _sync_instance = BalanceSync(
            auth_module=auth or TradovateAuth(),
            risk_engine=risk_engine
        )
    return _sync_instance


def init_balance_sync(risk_engine):
    """
    Initialize the balance sync singleton with a risk engine.
    Calls startup_sync and returns the instance.
    """
    sync = get_balance_sync(risk_engine=risk_engine)
    sync.risk_engine = risk_engine
    sync.startup_sync()
    return sync


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    from lucid_risk_engine import LucidRiskEngine
    from tradovate_auth import TradovateAuth

    engine = LucidRiskEngine()
    auth = TradovateAuth()
    sync = BalanceSync(auth_module=auth, risk_engine=engine)

    print("\n=== Testing startup_sync ===")
    result = sync.startup_sync()
    print(f"Startup sync {'succeeded' if result else 'failed'}")

    print("\n=== Sync info ===")
    print(json.dumps(sync.get_sync_info(), indent=2))
    print(json.dumps(engine.get_status(), indent=2))
