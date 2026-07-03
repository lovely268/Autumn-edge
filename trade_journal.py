"""
Trade Journal — SQLite-backed performance tracking for The Aurum Edge.
Records every trade entry, exit, and provides win rate statistics
for Kelly Criterion calibration and performance dashboards.
"""
import sqlite3
import json
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_journal.db")


class TradeJournal:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create schema if not exists."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc   TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                direction       TEXT NOT NULL,
                entry_price     REAL NOT NULL,
                exit_price      REAL,
                stop_loss       REAL,
                take_profit     REAL,
                quantity        INTEGER NOT NULL,
                conviction      REAL NOT NULL,
                regime          TEXT,
                scenario        TEXT,
                silver_bullet   BOOLEAN DEFAULT 0,
                gate_failures   TEXT,
                session         TEXT,
                entry_reason    TEXT,
                exit_reason     TEXT,
                pnl             REAL,
                pnl_pct         REAL,
                rr_realized     REAL,
                duration_minutes INTEGER,
                fees            REAL DEFAULT 0.0,
                tags            TEXT,
                notes           TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp
            ON trades(timestamp_utc)
        """)
        conn.commit()
        conn.close()

    def log_entry(self, symbol, direction, entry_price, stop_loss, take_profit,
                  quantity, conviction, regime, scenario, silver_bullet,
                  session, entry_reason, gate_failures=None):
        """Record a new trade entry."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO trades
                (timestamp_utc, symbol, direction, entry_price, stop_loss,
                 take_profit, quantity, conviction, regime, scenario,
                 silver_bullet, session, entry_reason, gate_failures)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            symbol, direction, entry_price, stop_loss,
            take_profit, quantity, conviction, regime, scenario,
            1 if silver_bullet else 0, session, entry_reason,
            json.dumps(gate_failures or [])
        ))
        conn.commit()
        conn.close()

    def log_exit(self, trade_id, exit_price, exit_reason, pnl, pnl_pct, fees=0.0, notes=None):
        """Record trade exit and calculate derived fields."""
        conn = sqlite3.connect(self.db_path)

        # First get entry details for calculations
        cursor = conn.execute(
            "SELECT entry_price, timestamp_utc FROM trades WHERE id = ?",
            (trade_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return

        entry_price = row[0]
        entry_time = datetime.fromisoformat(row[1])
        duration = (datetime.now(timezone.utc) - entry_time).total_seconds() / 60.0

        # Determine tags
        tags = "win" if pnl > 0 else ("loss" if pnl < 0 else "be")

        conn.execute("""
            UPDATE trades SET
                exit_price = ?, exit_reason = ?, pnl = ?, pnl_pct = ?,
                duration_minutes = ?, fees = ?, tags = ?, notes = ?
            WHERE id = ?
        """, (exit_price, exit_reason, pnl, pnl_pct,
              int(duration), fees, tags, notes, trade_id))
        conn.commit()
        conn.close()

    def get_stats(self):
        """Return summary statistics for dashboard/health_check."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN tags = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN tags = 'loss' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN tags = 'be' THEN 1 ELSE 0 END) as breaks,
                COALESCE(SUM(pnl), 0) as total_pnl,
                COALESCE(AVG(pnl), 0) as avg_pnl,
                COALESCE(AVG(conviction), 0) as avg_conviction,
                COALESCE(MAX(pnl), 0) as best_trade,
                COALESCE(MIN(pnl), 0) as worst_trade
            FROM trades
        """)
        stats = dict(cursor.fetchone())
        conn.close()

        total = stats["total"]
        if total > 0:
            stats["win_rate"] = round(stats["wins"] / total * 100, 1)
        else:
            stats["win_rate"] = 0.0

        return stats

    def get_recent_trades(self, limit=10):
        """Return most recent trades for dashboard."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM trades ORDER BY timestamp_utc DESC LIMIT ?",
            (limit,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def calibrate_kelly_blend(self, conviction=7.0):
        """
        Calculate the blended win rate for Kelly calibration.
        Returns dict with rolling_win_rate and recommended blend ratio.
        """
        stats = self.get_stats()
        total = stats["total"]

        if total < 20:
            return {
                "status": "insufficient_data",
                "trades_needed": 20 - total,
                "blended_p": conviction / 10.0  # Fall back to pure conviction
            }

        empirical_win_rate = stats["win_rate"] / 100.0

        # Determine blend ratio based on trade count
        if total < 50:
            theory_weight, empirical_weight = 0.7, 0.3
        elif total < 100:
            theory_weight, empirical_weight = 0.6, 0.4
        elif total < 200:
            theory_weight, empirical_weight = 0.5, 0.5
        else:
            theory_weight, empirical_weight = 0.4, 0.6

        blended_p = theory_weight * (conviction / 10.0) + empirical_weight * empirical_win_rate

        return {
            "total_trades": total,
            "empirical_win_rate": round(empirical_win_rate, 3),
            "theory_weight": theory_weight,
            "empirical_weight": empirical_weight,
            "blended_p": round(blended_p, 3),
            "status": "ready"
        }

    def get_regime_breakdown(self):
        """Return win rate breakdown by market regime."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT
                regime,
                COUNT(*) as total,
                SUM(CASE WHEN tags = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN tags = 'loss' THEN 1 ELSE 0 END) as losses
            FROM trades
            WHERE regime IS NOT NULL
            GROUP BY regime
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        for row in rows:
            if row["total"] > 0:
                row["win_rate"] = round(row["wins"] / row["total"] * 100, 1)
            else:
                row["win_rate"] = 0.0
        return rows

    def get_best_scenario(self):
        """Return which scenario type has the highest win rate."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT
                scenario,
                COUNT(*) as total,
                SUM(CASE WHEN tags = 'win' THEN 1 ELSE 0 END) as wins
            FROM trades
            WHERE scenario IS NOT NULL AND total > 5
            GROUP BY scenario
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        if not rows:
            return None
        best = max(rows, key=lambda r: (r["wins"] / r["total"]) if r["total"] > 0 else 0)
        best["win_rate"] = round(best["wins"] / best["total"] * 100, 1) if best["total"] > 0 else 0.0
        return best


# Module-level singleton for convenience
_journal_instance = None


def get_journal():
    global _journal_instance
    if _journal_instance is None:
        _journal_instance = TradeJournal()
    return _journal_instance


if __name__ == "__main__":
    # Self-test
    j = get_journal()
    print("Stats:", j.get_stats())

    # Test calibrate
    print("Calibrate:", j.calibrate_kelly_blend(conviction=8.0))

    # Test recent
    print("Recent:", j.get_recent_trades(3))