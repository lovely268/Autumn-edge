import os

# Session times in UTC (EDT = UTC-4)
ASIAN_SESSION_START = 0
ASIAN_SESSION_END = 4
LONDON_SESSION_START = 7
LONDON_SESSION_END = 8
NY_SESSION_START = 13
NY_SESSION_END = 20

# Global Entry Gates (UTC)
GLOBAL_ENTRY_END_UTC = 15 # 11:00 AM ET (End of NY Open Kill Zone for sniper entries)
FRIDAY_STOP_UTC = 16 # 12:00 PM ET
SUNDAY_START_UTC = 21 # 5:00 PM ET
HARD_CLOSE_UTC = 20.5 # 4:30 PM ET

# Pair Tiers & Rules
TIER_1 = ["ES=F", "NQ=F", "GC=F"]
TIER_2 = ["CL=F", "RTY=F", "YM=F"]
TIER_3 = ["MES=F", "MNQ=F", "MCL=F", "MGC=F"]

MIN_SCORES = {
    "TIER_1": 5,
    "TIER_2": 6,
    "TIER_3": 7,
    "TIER_4": 8
}

SPREAD_LIMITS = {
    "TIER_1": 1.0, # Points for Futures
    "TIER_2": 2.0,
    "TIER_3": 1.0,
    "TIER_4": 4.0
}

# Session Gates (UTC)
# Format: { symbol: [(start_hour_decimal, end_hour_decimal), ...] }
SESSION_GATES = {
    "ES=F": [(7.0, 10.0), (13.5, 15.0)], # London and NY Open Kill Zones
    "NQ=F": [(7.0, 10.0), (13.5, 15.0)],
    "GC=F": [(7.0, 10.0), (13.5, 15.0)], 
    "CL=F": [(13.0, 15.0)]  # Oil Pit open focus
}

# Win Rate Optimization - Circuit Breaker
CIRCUIT_BREAKER_2_LOSS_RISK = 0.005 # Reduce to 0.5% risk after 2 losses
CIRCUIT_BREAKER_3_LOSS_PAUSE_HOURS = 4
CIRCUIT_BREAKER_4_LOSS_HALT_DAY = True

# MGC Stop Parameters — minimum 20 ticks, maximum 40 ticks
MGC_TICK_SIZE = 0.10
MGC_TICK_VALUE = 1.0
MGC_MIN_STOP_TICKS = 20
MGC_MAX_STOP_TICKS = 40
MGC_SL_MULT = 1.0  # Pine Script default

# Asia Trading Days — only Mon/Tue
ASIA_TRADING_DAYS = [0, 1]  # Monday=0, Tuesday=1
ASIA_RANGE_MIN_TICKS = 15  # Skip if Asia range < 15 ticks on MGC

# Silver Bullet Window (9:50-10:10 AM ET = 13:50-14:10 UTC)
SILVER_BULLET_START = 13 + 50/60.0  # 13:50 UTC
SILVER_BULLET_END = 14 + 10/60.0   # 14:10 UTC
SILVER_BULLET_BOOST = 1.5  # Conviction boost

# Weekend Gap Risk — Friday hard close + Sunday block
FRIDAY_HARD_CLOSE_UTC = 20.5  # 4:30 PM ET Friday
SUNDAY_ENTRY_BLOCK_UTC = 21.0  # No entries before 5:00 PM ET Sunday (market opens 6 PM ET)
FRIDAY_EARLY_STOP_UTC = 17.0  # No new entries after 1:00 PM ET Friday

# Daily Bias — trade with the larger trend
DAILY_BIAS_FAST_EMA = 9
DAILY_BIAS_SLOW_EMA = 20
DAILY_BIAS_BOOST = 1.0  # Conviction boost when aligned with daily bias

# Scenario Detection
SCENARIOS = {
    "trending": {"min_atr_pct": 0.008, "min_daily_range_pct": 0.015},
    "ranging": {"max_atr_pct": 0.005, "min_daily_range_pct": 0.008},
    "volatile": {"min_atr_pct": 0.012},
    "quiet": {"max_atr_pct": 0.003, "max_daily_range_pct": 0.006},
}

# Risk & Correlation Protection
MAX_CONCURRENT_POSITIONS = 1
MAX_CURRENCY_EXPOSURE = 1
DAILY_LOSS_LIMIT_PCT = 0.02 # 2% ($500 for 25K)
RISK_PER_TRADE = 0.01 # 1% per trade ($250 for 25K)

# Optimized Parameters
SYMBOLS = [
    "ES=F", "NQ=F", "RTY=F", "YM=F",
    "GC=F", "HG=F", "CL=F", "NG=F",
    "EUR=X", "GBP=X", "JPY=X" # Currency Futures proxies
]

# Ensure Gold is included if needed (Yahoo symbol is GC=F)
if "GC=F" not in SYMBOLS: SYMBOLS.append("GC=F")

SYMBOL = "NQ=F"
INTERVAL = "5m"
CONFIRMATION_INTERVAL = "1m"
HTF_INTERVAL = "1h"
RR_RATIO = 4.0
DISP_MULT = 3.0
ACCOUNT_SIZE = 25000

# HTF Trend Filter
HTF_EMA_PERIOD = 20
MTF_INTERVAL = "15m"

# Advanced Institutional Features
NEWS_PAUSE_MINUTES = 30
TOTAL_EQUITY_HALT_PCT = 0.05 # 5% total ($1250)

# Persistence - Now relative for portability
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_DIR = os.path.dirname(BASE_DIR)
STATE_FILE = os.path.join(BASE_DIR, "market_state.json")
PORTFOLIO_FILE = os.path.join(BASE_DIR, "portfolio.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# Prop Firm Profiles (Type 5A)
# Options: None, "FTMO", "THE5ERS", "APEX", "LUCID"
PROP_FIRM_MODE = os.getenv("PROP_FIRM_MODE", "LUCID")

PROP_FIRM_RULES = {
    "FTMO": {
        "DAILY_LOSS_LIMIT_PCT": 0.045, # Safety margin below 5%
        "TOTAL_EQUITY_HALT_PCT": 0.09,  # Safety margin below 10%
        "MAX_CONCURRENT_POSITIONS": 2
    },
    "THE5ERS": {
        "DAILY_LOSS_LIMIT_PCT": 0.03,
        "TOTAL_EQUITY_HALT_PCT": 0.05,
        "MAX_CONCURRENT_POSITIONS": 1
    },
    "APEX": {
        "DAILY_LOSS_LIMIT_PCT": 0.03,
        "TOTAL_EQUITY_HALT_PCT": 0.04, # Apex has tighter trailing drawdown
        "MAX_CONCURRENT_POSITIONS": 3
    },
    "LUCID": {
        "DAILY_LOSS_LIMIT_PCT": 0.02, # $500 limit on 25K
        "TOTAL_EQUITY_HALT_PCT": 0.06, # $1500 limit on 25K
        "MAX_CONCURRENT_POSITIONS": 1,
        "RISK_PER_TRADE": 0.005 # Conservative 0.5% ($125) for Flex
    }
}


if PROP_FIRM_MODE in PROP_FIRM_RULES:
    rules = PROP_FIRM_RULES[PROP_FIRM_MODE]
    DAILY_LOSS_LIMIT_PCT = rules.get("DAILY_LOSS_LIMIT_PCT", DAILY_LOSS_LIMIT_PCT)
    TOTAL_EQUITY_HALT_PCT = rules.get("TOTAL_EQUITY_HALT_PCT", TOTAL_EQUITY_HALT_PCT)
    MAX_CONCURRENT_POSITIONS = rules.get("MAX_CONCURRENT_POSITIONS", MAX_CONCURRENT_POSITIONS)

# Oanda API - Pulling from environment variables
LIVE_MODE = True
OANDA_API_KEY = os.getenv("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "")
OANDA_ENVIRONMENT = os.getenv("OANDA_ENV", "live").lower()
OANDA_INSTRUMENT = "GBP_JPY"

# Telegram Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
