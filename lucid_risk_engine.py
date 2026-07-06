"""
Lucid Flex 25K Evaluation — Risk Engine & Tracker
Enforces all prop firm rules: daily profit cap, daily loss limit, consistency rule,
account floor, circuit breakers, and Kelly Criterion position sizing.
v2.1 — Resilient state management with audit logging and session tracking.
"""
import os
import json
import logging
from datetime import datetime, timezone, date, timedelta

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lucid_state.json")
STATE_BACKUP_PATH = STATE_PATH + ".bak"
STATE_VERSION = 2

log = logging.getLogger("risk")

# ── Lucid Flex 25K Parameters ──
ACCOUNT_SIZE = 25000
DAILY_PROFIT_TARGET = 250
DAILY_PROFIT_CAP = 600
DAILY_STOP_LOSS = -300
CONSISTENCY_MAX_PCT = 0.45
ACCOUNT_FLOOR = 24000
ACCOUNT_FLOOR_WARN = 24200
MAX_DAILY_LOSS = ACCOUNT_SIZE * 0.02
TOTAL_DRAWDOWN = ACCOUNT_SIZE * 0.06

INSTRUMENTS = {
    "MGC": {"point_value": 10.0, "tick_size": 0.1, "max_contracts": 8, "name": "Micro Gold"},
    "MES": {"point_value": 5.0,  "tick_size": 0.25, "max_contracts": 6, "name": "Micro S&P 500"},
    "MNQ": {"point_value": 2.0,  "tick_size": 0.25, "max_contracts": 10, "name": "Micro Nasdaq 100"},
}


def get_current_session(now_utc=None):
    """Determine the current trading session label based on UTC time."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour + now_utc.minute / 60.0
    weekday = now_utc.weekday()

    # Weekday-specific
    if weekday == 5 or weekday == 6:
        return "weekend"

    # Session windows (all ET converted to UTC approx)
    # Asian session: 8PM-12AM ET = 0-4 UTC (technically 1AM-5AM? no... 8PM ET = 0 UTC next day)
    # Actually: Asia = 7PM-3AM ET = 23-7 UTC. Let's use config constants.
    from config import ASIAN_SESSION_START, ASIAN_SESSION_END, LONDON_SESSION_START, LONDON_SESSION_END, \
        NY_SESSION_START, NY_SESSION_END, SILVER_BULLET_START, SILVER_BULLET_END, \
        FRIDAY_EARLY_STOP_UTC, HARD_CLOSE_UTC

    if ASIAN_SESSION_START <= hour < ASIAN_SESSION_END:
        return "asia"
    if LONDON_SESSION_START <= hour < LONDON_SESSION_END:
        return "london"
    if NY_SESSION_START <= hour < NY_SESSION_END:
        if SILVER_BULLET_START <= hour < SILVER_BULLET_END:
            return "silver_bullet"
        return "ny_open"
    if hour >= HARD_CLOSE_UTC:
        return "hard_close"
    if weekday == 4 and hour >= FRIDAY_EARLY_STOP_UTC:
        return "friday_close"
    return "after_hours"


class LucidRiskEngine:
    def __init__(self):
        self.state = self._load_state()
        self._reset_if_new_day()

    # ── Persistence ──
    def _defaults(self):
        return {
            "version": STATE_VERSION,
            "balance": ACCOUNT_SIZE,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "last_date": str(date.today()),
            "consistency_days": {},
            "consecutive_losses": 0,
            "pause_until": None,
            "positions": {},
            "trades_today": 0,
            "trading_days": [],
            "daily_high_watermark": ACCOUNT_SIZE,
            "peak_balance": ACCOUNT_SIZE,
            "pass_alert_sent": False,
            "last_action": None,
            "last_action_time": None,
        }

    def _load_state(self):
        defaults = self._defaults()
        if not os.path.exists(STATE_PATH):
            return defaults
        try:
            with open(STATE_PATH) as f:
                data = json.load(f)
            # Migrate from older version if needed
            if data.get("version", 1) < STATE_VERSION:
                log.info(f"Migrating state from v{data.get('version', 1)} to v{STATE_VERSION}")
                # Apply defaults for any missing keys
                data = {**defaults, **data, "version": STATE_VERSION}
            return {**defaults, **data}
        except (json.JSONDecodeError, ValueError, OSError) as e:
            log.error(f"Corrupted state file: {e}")
            # Try backup
            if os.path.exists(STATE_BACKUP_PATH):
                try:
                    with open(STATE_BACKUP_PATH) as f:
                        data = json.load(f)
                    log.warning("Recovered from backup state file")
                    return {**defaults, **data}
                except Exception:
                    pass
            log.warning("Could not recover — starting with fresh defaults")
            return defaults

    def _save_state(self):
        # Write to temp, then atomic replace, then backup
        temp = STATE_PATH + ".tmp"
        try:
            with open(temp, "w") as f:
                json.dump(self.state, f, indent=2)
            os.replace(temp, STATE_PATH)
            # Keep a backup copy
            with open(STATE_BACKUP_PATH, "w") as f:
                json.dump(self.state, f, indent=2)
        except OSError as e:
            log.error(f"Failed to save state: {e}")

    def _track_action(self, action):
        """Record the last action for audit trail."""
        self.state["last_action"] = action
        self.state["last_action_time"] = datetime.now(timezone.utc).isoformat()

    def _reset_if_new_day(self):
        today = str(date.today())
        if self.state["last_date"] != today:
            prev_date = self.state["last_date"]
            prev_pnl = self.state["daily_pnl"]
            # Archive yesterday's PnL for consistency check
            if prev_pnl != 0:
                self.state["consistency_days"][prev_date] = prev_pnl
            log.info(f"Day rollover: {prev_date} PnL=${prev_pnl:.2f} → {today}")
            self.state["daily_pnl"] = 0.0
            self.state["trades_today"] = 0
            self.state["daily_high_watermark"] = self.state["balance"]
            self.state["last_date"] = today
            self.state["pause_until"] = None
            self._track_action(f"day_rollover:{prev_date}")
            self._check_pass_conditions()
            self._save_state()

    # ── Rule Checks ──
    def check_gate(self, symbol, direction, price, conviction):
        self._reset_if_new_day()
        reasons = []

        # 1. Daily Profit Cap ($600)
        if self.state["daily_pnl"] >= DAILY_PROFIT_CAP:
            return {"allowed": False, "reason": f"Daily profit cap (${DAILY_PROFIT_CAP}) reached", "risk_pct": 0}

        # 2. Daily Stop Loss (-$300)
        if self.state["daily_pnl"] <= DAILY_STOP_LOSS:
            return {"allowed": False, "reason": f"Daily stop loss (${DAILY_STOP_LOSS}) hit", "risk_pct": 0}

        # 3. Daily Loss Limit (2% = $500)
        if self.state["daily_pnl"] <= -MAX_DAILY_LOSS:
            return {"allowed": False, "reason": f"Daily loss limit (${MAX_DAILY_LOSS}) reached", "risk_pct": 0}

        # 4. Total Drawdown (6% = $1500)
        drawdown = ACCOUNT_SIZE - self.state["balance"]
        if drawdown >= TOTAL_DRAWDOWN:
            return {"allowed": False, "reason": f"Total drawdown limit (${TOTAL_DRAWDOWN}) reached", "risk_pct": 0}

        # 5. Account Floor ($24,000)
        if self.state["balance"] <= ACCOUNT_FLOOR:
            return {"allowed": False, "reason": f"Account floor (${ACCOUNT_FLOOR}) breached", "risk_pct": 0}

        # 6. Circuit Breaker: 4 consecutive losses → day halt
        if self.state["consecutive_losses"] >= 4:
            return {"allowed": False, "reason": "4 consecutive losses — day halted", "risk_pct": 0}

        # 7. Circuit Breaker: 3 losses → 4-hour pause
        pause_until = self.state.get("pause_until")
        if pause_until:
            pause_time = datetime.fromisoformat(pause_until)
            if datetime.now(timezone.utc) < pause_time:
                remaining = (pause_time - datetime.now(timezone.utc)).total_seconds() / 60
                return {"allowed": False, "reason": f"3-loss pause active ({remaining:.0f} min remaining)", "risk_pct": 0}
            self.state["pause_until"] = None
            log.info("3-loss pause expired — resuming trading")

        # 8. Consistency Rule
        if self.state["total_pnl"] > 0:
            current_day_pct = abs(self.state["daily_pnl"]) / abs(self.state["total_pnl"] + abs(self.state["daily_pnl"]))
            if current_day_pct > CONSISTENCY_MAX_PCT:
                return {"allowed": False, "reason": f"Consistency rule: this day would exceed {CONSISTENCY_MAX_PCT*100:.0f}% of total"}

        # 9. Instrument Max Contracts check
        instr = INSTRUMENTS.get(symbol)
        if not instr:
            return {"allowed": False, "reason": f"Unknown instrument {symbol}"}

        # 10. Minimum conviction score
        min_score = 5.0
        if conviction < min_score:
            return {"allowed": False, "reason": f"Conviction {conviction}/10 below minimum {min_score}"}

        # ── Calculate Kelly Risk % ──
        risk_pct = self._kelly_criterion(conviction)
        if self.state["consecutive_losses"] >= 2:
            risk_pct *= 0.5

        return {"allowed": True, "reason": "ok", "risk_pct": risk_pct}

    # ── Kelly Criterion ──
    def _kelly_criterion(self, conviction):
        p = conviction / 10.0
        b = 2.0
        f_star = (p * (b + 1) - 1) / b
        if f_star < 0:
            f_star = 0
        risk = f_star * 0.015
        return max(0.005, min(0.015, risk))

    # ── Position Sizing ──
    def calculate_contracts(self, symbol, direction, price, conviction, sl_dist=None):
        instr = INSTRUMENTS.get(symbol)
        if not instr:
            return 0

        risk_pct = self._kelly_criterion(conviction)
        risk_amount = self.state["balance"] * risk_pct

        if sl_dist is None or sl_dist <= 0:
            sl_dist = price * 0.005

        point_value = instr["point_value"]
        if sl_dist <= 0:
            return 0
        contracts = int(risk_amount / (sl_dist * point_value))
        contracts = max(1, min(contracts, instr["max_contracts"]))
        log.info(f"SIZING: {symbol} risk${risk_amount:.2f} sl_dist={sl_dist:.2f} point_val={point_value} → {contracts} contracts")
        return contracts

    # ── State Recording ──
    def record_entry(self, symbol, direction, price, contracts, conviction):
        today = str(date.today())
        if today not in self.state["trading_days"]:
            self.state["trading_days"].append(today)

        self.state["positions"][symbol] = {
            "direction": direction,
            "price": price,
            "contracts": contracts,
            "conviction": conviction,
            "entry_time": datetime.now(timezone.utc).isoformat()
        }
        self.state["trades_today"] += 1
        self._track_action(f"entry:{symbol}:{direction}:{contracts}@${price}")
        log.info(f"ENTRY: {direction.upper()} {contracts}x {symbol} @ ${price} | balance=${self.state['balance']:.2f}")
        self._check_pass_conditions()
        self._save_state()

    def record_exit(self, symbol, pnl, pnl_pct):
        old_balance = self.state["balance"]
        self.state["balance"] += pnl
        self.state["daily_pnl"] += pnl
        self.state["total_pnl"] += pnl

        # Update high watermark
        if self.state["balance"] > self.state["peak_balance"]:
            self.state["peak_balance"] = self.state["balance"]
        if self.state["balance"] > self.state["daily_high_watermark"]:
            self.state["daily_high_watermark"] = self.state["balance"]

        # Circuit breaker tracking
        if pnl < 0:
            self.state["consecutive_losses"] += 1
            if self.state["consecutive_losses"] == 3:
                pause_end = datetime.now(timezone.utc) + timedelta(hours=4)
                self.state["pause_until"] = pause_end.isoformat()
                log.warning(f"3 consecutive losses hit — 4-hour pause until {pause_end}")
        else:
            self.state["consecutive_losses"] = 0

        # Remove from active positions
        self.state["positions"].pop(symbol, None)

        pnl_label = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BE")
        log.info(f"EXIT: {symbol} {pnl_label} pnl=${pnl:.2f} bal=${old_balance:.2f}→${self.state['balance']:.2f} daily=${self.state['daily_pnl']:.2f}")
        self._track_action(f"exit:{symbol}:{pnl_label}:${pnl:.2f}")
        self._check_pass_conditions()
        self._save_state()

    # ── Pass Condition Checking ──
    def _check_pass_conditions(self):
        profit_ok = self.state["total_pnl"] >= 1250
        consistency_ok = self._consistency_check()
        floor_ok = self.state["balance"] >= ACCOUNT_FLOOR
        days_ok = len(self.state.get("trading_days", [])) >= 2
        all_met = profit_ok and consistency_ok and floor_ok and days_ok

        if all_met and not self.state.get("pass_alert_sent", False):
            self.state["pass_alert_sent"] = True
            self._save_state()
            msg = "🚀 EVALUATION PASS CONDITIONS MET — Log into Lucid dashboard and request pass NOW"
            log.info(msg)
            return msg

        return None

    def _consistency_check(self):
        total_abs = sum(abs(v) for v in self.state["consistency_days"].values()) + abs(self.state["daily_pnl"])
        if total_abs <= 0:
            return True
        values = [abs(v) / total_abs for v in self.state["consistency_days"].values()]
        if self.state["daily_pnl"] != 0:
            values.append(abs(self.state["daily_pnl"]) / total_abs)
        max_day_pct = max(values) if values else 0
        return max_day_pct <= CONSISTENCY_MAX_PCT

    # ── Status / Health ──
    def get_status(self):
        self._reset_if_new_day()
        remaining_target = max(0, 1250 - self.state["total_pnl"])
        remaining_cap = max(0, DAILY_PROFIT_CAP - self.state["daily_pnl"])
        drawdown = ACCOUNT_SIZE - self.state["balance"]
        peak_to_dd = (self.state["peak_balance"] - self.state["balance"]) / max(self.state["peak_balance"], 1) * 100

        profit_ok = self.state["total_pnl"] >= 1250
        consistency_ok = self._consistency_check()
        floor_ok = self.state["balance"] >= ACCOUNT_FLOOR
        days_ok = len(self.state.get("trading_days", [])) >= 2

        now = datetime.now(timezone.utc)
        current_session = get_current_session(now)
        hour_et = (now.hour - 4 + now.minute / 60.0) % 24

        return {
            "status": "PASSED" if profit_ok and consistency_ok and floor_ok and days_ok else "ACTIVE",
            "service": "Aurum Edge Webhook",
            "version": "2.2",
            "balance": round(self.state["balance"], 2),
            "daily_pnl": round(self.state["daily_pnl"], 2),
            "total_pnl": round(self.state["total_pnl"], 2),
            "profit_target_remaining": round(remaining_target, 2),
            "daily_cap_remaining": round(remaining_cap, 2),
            "drawdown": round(drawdown, 2),
            "peak_drawdown_pct": round(peak_to_dd, 2),
            "account_floor_warning": self.state["balance"] <= ACCOUNT_FLOOR_WARN,
            "consecutive_losses": self.state["consecutive_losses"],
            "pause_active": self.state.get("pause_until") is not None,
            "trading_days": len(self.state.get("trading_days", [])),
            "trades_today": self.state["trades_today"],
            "open_positions": self.state["positions"],
            "current_session": current_session,
            "session_info": {
                "label": current_session,
                "time_utc": now.strftime("%H:%M:%S"),
                "time_et": f"{int(hour_et):02d}:{int((hour_et % 1) * 60):02d}",
                "weekday": now.strftime("%A"),
            },
            "pass_conditions": {
                "profit_target_1250": profit_ok,
                "consistency_50pct": consistency_ok,
                "account_floor_24k": floor_ok,
                "min_trading_days_2": days_ok,
                "all_met": all([profit_ok, consistency_ok, floor_ok, days_ok])
            },
            "pass_alert_sent": self.state.get("pass_alert_sent", False),
            "last_action": self.state.get("last_action"),
            "last_action_time": self.state.get("last_action_time"),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    engine = LucidRiskEngine()
    print(json.dumps(engine.get_status(), indent=2))

    # Test gate
    gate = engine.check_gate("MGC", "long", 2350.0, 8.5)
    print(f"Gate: {gate}")

    if gate["allowed"]:
        contracts = engine.calculate_contracts("MGC", "long", 2350.0, 8.5)
        print(f"Contracts: {contracts}")