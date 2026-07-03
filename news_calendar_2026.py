"""
The Aurum Edge — News Blackout Calendar 2026
Scheduled high-impact economic release events with blackout windows.
Tier 1: Scheduled events (FOMC, NFP, CPI, PPI, Powell, ECB, BOE)
Tier 2: Geopolitical deviation (manual override via JSON)
"""
from datetime import datetime, timezone, timedelta


def _utc(y, m, d, h, mi=0):
    """Helper to create UTC datetimes."""
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# Each event: (datetime_utc, event_name, impact_level, affected_assets)
# impact_level: "extreme" | "high" | "medium"
# Blackout window: 30 min before to 30 min after (extreme = 45 min)

SCHEDULED_EVENTS = [
    # ── FOMC Meetings 2026 ──
    # FOMC statements at 14:00 ET (18:00 UTC), presser at 14:30 ET
    (_utc(2026, 1, 29, 18, 0),   "FOMC Statement", "extreme", "all"),
    (_utc(2026, 3, 19, 18, 0),   "FOMC Statement + SEP", "extreme", "all"),
    (_utc(2026, 5, 7, 18, 0),    "FOMC Statement", "extreme", "all"),
    (_utc(2026, 6, 18, 18, 0),   "FOMC Statement + SEP", "extreme", "all"),
    (_utc(2026, 7, 30, 18, 0),   "FOMC Statement", "extreme", "all"),
    (_utc(2026, 9, 17, 18, 0),   "FOMC Statement + SEP", "extreme", "all"),
    (_utc(2026, 11, 5, 18, 0),   "FOMC Statement", "extreme", "all"),
    (_utc(2026, 12, 17, 18, 0),  "FOMC Statement + SEP", "extreme", "all"),

    # ── NFP (Non-Farm Payrolls) — First Friday, 8:30 ET (12:30 UTC) ──
    (_utc(2026, 1, 9, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 2, 6, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 3, 6, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 4, 3, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 5, 1, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 6, 5, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 7, 3, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 8, 7, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 9, 4, 12, 30),   "NFP", "extreme", "all"),
    (_utc(2026, 10, 2, 12, 30),  "NFP", "extreme", "all"),
    (_utc(2026, 11, 6, 12, 30),  "NFP", "extreme", "all"),
    (_utc(2026, 12, 4, 12, 30),  "NFP", "extreme", "all"),

    # ── CPI (Consumer Price Index) — 8:30 ET (12:30 UTC), mid-month ──
    (_utc(2026, 1, 14, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 2, 13, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 3, 12, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 4, 14, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 5, 13, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 6, 11, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 7, 15, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 8, 12, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 9, 11, 12, 30),  "CPI", "high", "all"),
    (_utc(2026, 10, 14, 12, 30), "CPI", "high", "all"),
    (_utc(2026, 11, 13, 12, 30), "CPI", "high", "all"),
    (_utc(2026, 12, 11, 12, 30), "CPI", "high", "all"),

    # ── PPI (Producer Price Index) — 8:30 ET, day after CPI ──
    (_utc(2026, 1, 15, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 2, 14, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 3, 13, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 4, 15, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 5, 14, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 6, 12, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 7, 16, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 8, 13, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 9, 14, 12, 30),  "PPI", "high", "all"),
    (_utc(2026, 10, 15, 12, 30), "PPI", "high", "all"),
    (_utc(2026, 11, 14, 12, 30), "PPI", "high", "all"),
    (_utc(2026, 12, 14, 12, 30), "PPI", "high", "all"),

    # ── Fed Chair Powell Testimony / Pressers ──
    (_utc(2026, 3, 3, 14, 0),    "Powell Semi-Annual Testimony", "high", "all"),
    (_utc(2026, 7, 15, 14, 0),   "Powell Semi-Annual Testimony", "high", "all"),

    # ── ECB Rate Decisions ──
    (_utc(2026, 1, 30, 12, 45),  "ECB Rate Decision", "high", "all"),
    (_utc(2026, 3, 13, 12, 45),  "ECB Rate Decision", "high", "all"),
    (_utc(2026, 4, 17, 12, 45),  "ECB Rate Decision", "high", "all"),
    (_utc(2026, 6, 5, 12, 45),   "ECB Rate Decision", "high", "all"),
    (_utc(2026, 7, 17, 12, 45),  "ECB Rate Decision", "high", "all"),
    (_utc(2026, 9, 11, 12, 45),  "ECB Rate Decision", "high", "all"),
    (_utc(2026, 10, 16, 12, 45), "ECB Rate Decision", "high", "all"),
    (_utc(2026, 12, 11, 12, 45), "ECB Rate Decision", "high", "all"),

    # ── BOE Rate Decisions ──
    (_utc(2026, 2, 6, 12, 0),    "BOE Rate Decision", "high", "all"),
    (_utc(2026, 5, 8, 12, 0),    "BOE Rate Decision", "high", "all"),
    (_utc(2026, 8, 7, 12, 0),    "BOE Rate Decision", "high", "all"),
    (_utc(2026, 11, 6, 12, 0),   "BOE Rate Decision", "high", "all"),
]

# Blackout windows (in minutes before and after event)
BLACKOUT_WINDOWS = {
    "extreme": 45,  # FOMC, NFP
    "high": 30,     # CPI, PPI, Powell testimony, ECB/BOE
    "medium": 15,   # Standard economic data
}

# Asset-specific impact mapping (which instruments to pause)
ASSET_IMPACT = {
    "all":          ["ES=F", "NQ=F", "MES=F", "MNQ=F", "GC=F", "MGC=F", "CL=F"],
    "us_indices":   ["ES=F", "NQ=F", "MES=F", "MNQ=F", "YM=F", "RTY=F"],
    "dxy_sensitive": ["ES=F", "NQ=F", "GC=F", "MGC=F", "CL=F", "EUR=X", "GBP=X"],
    "gold_specific": ["GC=F", "MGC=F"],
    "energy":       ["CL=F"],
}


def is_news_blackout(now_utc=None):
    """
    Check if current time falls within any news blackout window.

    Returns:
        dict with:
            "in_blackout": bool
            "event_name": str or None
            "minutes_remaining": int or None
            "impact_level": str or None
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    for event_dt, event_name, impact_level, _assets in SCHEDULED_EVENTS:
        window = BLACKOUT_WINDOWS.get(impact_level, 30)
        start = event_dt - timedelta(minutes=window)
        end = event_dt + timedelta(minutes=window)

        if start <= now_utc <= end:
            remaining = (end - now_utc).total_seconds() / 60
            return {
                "in_blackout": True,
                "event_name": event_name,
                "minutes_remaining": int(remaining),
                "impact_level": impact_level,
            }

    return {"in_blackout": False}


def get_next_event(now_utc=None):
    """Return the next scheduled event (for dashboard display)."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    for event_dt, event_name, impact_level, _assets in SCHEDULED_EVENTS:
        if event_dt > now_utc:
            hours_until = (event_dt - now_utc).total_seconds() / 3600
            return {
                "event": event_name,
                "utc_time": event_dt.isoformat(),
                "hours_until": round(hours_until, 1),
                "impact": impact_level
            }
    return None


def check_geopolitical_blackout(geo_path=None):
    """
    Check the geopolitical state JSON for manual overrides.
    Returns same format as is_news_blackout().
    """
    import json
    import os
    if geo_path is None:
        geo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geopolitical_state.json")

    try:
        with open(geo_path) as f:
            geo = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"in_blackout": False}

    if not geo.get("deviation_active", False):
        return {"in_blackout": False}

    blackout_end_utc = geo.get("blackout_end_utc")
    if not blackout_end_utc:
        return {"in_blackout": False}

    now_utc = datetime.now(timezone.utc)
    end_time = datetime.fromisoformat(blackout_end_utc)
    if now_utc < end_time:
        remaining = (end_time - now_utc).total_seconds() / 60
        return {
            "in_blackout": True,
            "event_name": f"Geopolitical: {geo.get('description', 'Unknown')}",
            "minutes_remaining": int(remaining),
            "impact_level": "extreme",
        }

    return {"in_blackout": False}


if __name__ == "__main__":
    # Self-test
    print("=== News Blackout Check ===")
    result = is_news_blackout()
    print(f"Now: {result}")

    print("\n=== Next Event ===")
    next_ev = get_next_event()
    print(f"Next: {next_ev}")

    print("\n=== Geopolitical Check ===")
    geo = check_geopolitical_blackout()
    print(f"Geo: {geo}")