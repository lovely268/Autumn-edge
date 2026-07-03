"""
Lucid Flex 25K Evaluation — Risk Engine & Tracker
Enforces all prop firm rules: daily profit cap, daily loss limit, consistency rule,
account floor, circuit breakers, and Kelly Criterion position sizing.
"""
import os
import json
import time
from datetime import datetime, timezone, date

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lucid_state.json")

# ── Lucid Flex 25K Parameters ──
ACCOUNT_SIZE = 25000
DAILY_PROFIT_TARGET = 250       # $250/day for 5-day pass
DAILY_PROFIT_CAP = 600          # No new entries after this
DAILY_STOP_LOSS = -300          # Hard halt
CONSISTENCY_MAX_PCT = 0.45      # Max 45% of total profit from a single day
ACCOUNT_FLOOR = 24000           # $24,000 warning
ACCOUNT_FLOOR_WARN = 24200      # Warning level
MAX_DAILY_LOSS = ACCOUNT_SIZE * 0.02  # $500 daily loss limit
TOTAL_DRAWDOWN = ACCOUNT_SIZE * 0.06  # $1500 total drawdown

# Instrument specs
INSTRUMENTS = {
    "MGC": {"point_value": 10.0, "tick_size": 0.1, "max_contracts": 8, "name": "Micro Gold"},
    "MES": {"point_value": 5.0,  "tick_size": 0.25, "max_contracts": 6, "name": "Micro S&P 500"},
}


class LucidRiskEngine:
    def __init__(self):
        self.state = self._load_state()
        self._reset_if_new_day()

    # ── Persistence ──
    def _load_state(self):
        defaults = {
            "balance": ACCOUNT_SIZE,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "last_date": str(date.today()),
            "consistency_days": {},    # {date_str: pnl}
            "consecutive_losses": 0,
            "pause_until": None,
            "positions": {},
            "trades_today": 0,
            "trading_days": [],          # List of date strings with at least one trade
            "daily_high_watermark": ACCOUNT_SIZE,
            "peak_balance": ACCOUNT_SIZE,
            "pass_alert_sent": False,    # True once pass SMS has been sent
        }
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH) as f:
                return {**defaults, **json.load(f)}
        return defaults

    def _save_state(self):
        temp = STATE_PATH + ".tmp"
        with open(temp, "w") as f:
            json.dump(self.state, f, indent=2)
        os.replace(temp, STATE_PATH)

    def _reset_if_new_day(self):
        today = str(date.today())
        if self.state["last_date"] != today:
            # Archive yesterday's PnL for consistency check
            if self.state["daily_pnl"] != 0:
                self.state["consistency_days"][self.state["last_date"]] = self.state["daily_pnl"]
            self.state["daily_pnl"] = 0.0
            self.state["trades_today"] = 0
            self.state["daily_high_watermark"] = self.state["balance"]
            self.state["last_date"] = today
            self.state["pause_until"] = None
            # Daily check: pass alert? No — only on significant events
            self._check_pass_conditions()
            self._save_state()

    # ── Rule Checks ──
    def check_gate(self, symbol, direction, price, conviction):
        """
        Full gate check before allowing an entry. Returns dict with:
          { "allowed": bool, "reason": str, "risk_pct": float }
        """
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
        if self.state.get("pause_until"):
            pause_time = datetime.fromisoformat(self.state["pause_until"])
            if datetime.now(timezone.utc) < pause_time:
                remaining = (pause_time - datetime.now(timezone.utc)).total_seconds() / 60
                return {"allowed": False, "reason": f"3-loss pause active ({remaining:.0f} min remaining)", "risk_pct": 0}
            self.state["pause_until"] = None

        # 8. Consistency Rule
        if self.state["total_pnl"] > 0:
            current_day_pct = abs(self.state["daily_pnl"]) / abs(self.state["total_pnl"] + abs(self.state["daily_pnl"]))
            if current_day_pct > CONSISTENCY_MAX_PCT:
                # Check if adding this trade would exceed 45%
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
        # Circuit breaker halving
        if self.state["consecutive_losses"] >= 2:
            risk_pct *= 0.5

        return {"allowed": True, "reason": "ok", "risk_pct": risk_pct}

    # ── Kelly Criterion ──
    def _kelly_criterion(self, conviction):
        """
        Full Kelly: f* = (p * (b + 1) - 1) / b
        p = conviction/10, b = 2.0 (conservative R:R floor)
        Scaled to 0.5% - 1.5% for prop firm safety.
        """
        p = conviction / 10.0
        b = 2.0
        f_star = (p * (b + 1) - 1) / b
        if f_star < 0:
            f_star = 0
        # Half-Kelly → scale to [0.005, 0.015]
        risk = f_star * 0.015
        return max(0.005, min(0.015, risk))

    # ── Position Sizing ──
    def calculate_contracts(self, symbol, direction, price, conviction):
        """Convert risk % to number of contracts."""
        instr = INSTRUMENTS.get(symbol)
        if not instr:
            return 0

        risk_pct = self._kelly_criterion(conviction)
        risk_amount = self.state["balance"] * risk_pct

        # Estimate SL distance as a fraction of price (0.5% for futures)
        sl_dist = price * 0.005

        point_value = instr["point_value"]
        contracts = int(risk_amount / (sl_dist * point_value))
        contracts = max(1, min(contracts, instr["max_contracts"]))
        return contracts

    # ── State Recording ──
    def record_entry(self, symbol, direction, price, contracts, conviction):
        today = str(date.today())
        # Track trading days — add the current date if not already present
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
        self._check_pass_conditions()
        self._save_state()

    def record_exit(self, symbol, pnl, pnl_pct):
        self.state["balance"] += pnl
        self.state["daily_pnl"] += pnl
        self.state["total_pnl"] += pnl

        # Update high watermark for drawdown calculations
        if self.state["balance"] > self.state["peak_balance"]:
            self.state["peak_balance"] = self.state["balance"]
        if self.state["balance"] > self.state["daily_high_watermark"]:
            self.state["daily_high_watermark"] = self.state["balance"]

        # Circuit breaker tracking
        if pnl < 0:
            self.state["consecutive_losses"] += 1
            if self.state["consecutive_losses"] == 3:
                self.state["pause_until"] = (
                    datetime.now(timezone.utc) + timedelta(hours=4)
                ).isoformat()
        else:
            self.state["consecutive_losses"] = 0

        # Remove from active positions
        self.state["positions"].pop(symbol, None)
        self._check_pass_conditions()
        self._save_state()

    # ── Pass Condition Checking ──
    def _check_pass_conditions(self):
        """
        Check all 4 Lucid Flex evaluation pass conditions.
        If ALL met and alert not yet sent, return alert message.
        """
        profit_ok = self.state["total_pnl"] >= 1250
        consistency_ok = self._consistency_check()
        floor_ok = self.state["balance"] >= ACCOUNT_FLOOR
        days_ok = len(self.state.get("trading_days", [])) >= 2

        all_met = profit_ok and consistency_ok and floor_ok and days_ok

        if all_met and not self.state.get("pass_alert_sent", False):
            self.state["pass_alert_sent"] = True
            self._save_state()
            msg = "EVALUATION PASS CONDITIONS MET — Log into Lucid dashboard and request pass NOW"
            print(f"🚀 {msg}", flush=True)
            return msg

        if all_met:
            return "PASS_CONDITIONS_MET_ALREADY_NOTIFIED"

        return None

    def _consistency_check(self):
        """Ensure largest single day <= 50% of total profit."""
        total_abs = sum(abs(v) for v in self.state["consistency_days"].values()) + abs(self.state["daily_pnl"])
        if total_abs <= 0:
            return True
        max_day_pct = max(
            [abs(v) / total_abs for v in self.state["consistency_days"].values()] +
            [abs(self.state["daily_pnl"]) / total_abs] * (1 if self.state["daily_pnl"] != 0 else 0)
        )
        return max_day_pct <= CONSISTENCY_MAX_PCT

    # ── Status / Health ──
    def get_status(self):
        """Return a dict for health_check / dashboard."""
        self._reset_if_new_day()
        remaining_target = max(0, 1250 - self.state["total_pnl"])
        remaining_cap = max(0, DAILY_PROFIT_CAP - self.state["daily_pnl"])
        drawdown = ACCOUNT_SIZE - self.state["balance"]
        peak_to_dd = (self.state["peak_balance"] - self.state["balance"]) / self.state["peak_balance"] * 100 if self.state["peak_balance"] > 0 else 0

        profit_ok = self.state["total_pnl"] >= 1250
        consistency_ok = self._consistency_check()
        floor_ok = self.state["balance"] >= ACCOUNT_FLOOR
        days_ok = len(self.state.get("trading_days", [])) >= 2
        pass_conditions = {
            "profit_target_1250": profit_ok,
            "consistency_50pct": consistency_ok,
            "account_floor_24k": floor_ok,
            "min_trading_days_2": days_ok,
            "all_met": all([profit_ok, consistency_ok, floor_ok, days_ok])
        }

        return {
            "status": "PASSED" if profit_ok and consistency_ok and floor_ok and days_ok else "ACTIVE",
            "service": "Aurum Edge Webhook",
            "version": "2.0",
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
            "open_positions": len(self.state["positions"]),
            "pass_conditions": pass_conditions,
            "pass_alert_sent": self.state.get("pass_alert_sent", False),
        }


if __name__ == "__main__":
    # Quick self-test
    engine = LucidRiskEngine()
    print(json.dumps(engine.get_status(), indent=2))

    # Test gate
    gate = engine.check_gate("MGC", "long", 2350.0, 8.5)
    print(f"Gate: {gate}")

    if gate["allowed"]:
        contracts = engine.calculate_contracts("MGC", "long", 2350.0, 8.5)
        print(f"Contracts: {contracts}")