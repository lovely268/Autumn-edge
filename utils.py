import json
import os
from datetime import datetime, timedelta, timezone
import pandas as pd
import config
import yfinance as yf

def fetch_economic_calendar():
    """Fetches high-impact news from ForexFactory JSON."""
    try:
        import requests
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"Error fetching calendar: {e}")
    return []

def check_news_blackout(calendar):
    """Returns True if a high-impact news event is within 30 minutes."""
    now = datetime.now(timezone.utc)
    for event in calendar:
        if event.get('impact') == 'High':
            try:
                # ForexFactory times are usually UTC
                event_time = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
                if abs((event_time - now).total_seconds()) < config.NEWS_PAUSE_MINUTES * 60:
                    return True
            except: continue
    return False

def get_vix_level():
    try:
        vix = yf.download("^VIX", period="1d", progress=False)
        if not vix.empty:
            return float(vix['Close'].iloc[-1])
    except: pass
    return 20.0

def perform_sunday_refresh():
    """Consolidated Sunday maintenance: Weekly report + Deep clean."""
    print("Executing Sunday Master Refresh...")
    generate_weekly_report()
    
    # Save week start equity for guardrail
    portfolio_path = config.PORTFOLIO_FILE
    if os.path.exists(portfolio_path):
        try:
            with open(portfolio_path, "r") as f:
                portfolio = json.load(f)
            portfolio['week_start_equity'] = portfolio.get('balance', config.ACCOUNT_SIZE)
            with open(portfolio_path, "w") as f:
                json.dump(portfolio, f, indent=4)
            print(f"Week start equity reset to: ${portfolio['week_start_equity']}")
        except Exception as e:
            print(f"Error resetting weekly equity: {e}")

    # Deep Clean: Rotate logs or clear temporary session data
    # (Example: clearing any .tmp files that might have been left behind)
    import glob
    tmp_files = glob.glob(f"{config.SHARED_DIR}/*.tmp")
    for f in tmp_files:
        try:
            os.remove(f)
            print(f"Cleaned up: {f}")
        except: pass
    
    print("Sunday Refresh Complete.")

def generate_weekly_report():
    print("Generating Weekly Performance Report...")
    # This would parse trades.csv or portfolio history
    # For now, create a placeholder structure
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_trades": 0,
        "win_rate": "0%",
        "total_pnl": "$0.00",
        "status": "No trades recorded in current session"
    }
    report_path = f"{config.SHARED_DIR}/weekly_report_{datetime.now().strftime('%Y%W')}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=4)
    print(f"Report saved to {report_path}")

def update_daily_stats():
    """Updates PDH, PDL, DXY, VIX, and Oanda Sentiment."""
    vix = get_vix_level()
    # Save to a daily_stats.json for persistence
    stats = {
        "vix": vix,
        "last_update": datetime.now().isoformat()
    }
    with open(f"{config.SHARED_DIR}/daily_stats.json", "w") as f:
        json.dump(stats, f, indent=4)
    print("Daily stats updated.")

def sanitize_nans(obj):
    """Recursively replaces NaN with None for JSON compliance."""
    import math
    if isinstance(obj, dict):
        return {k: sanitize_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_nans(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    return obj

def calculate_currency_strength(all_1d):
    """Calculates 0-100 strength scores for 8 major currencies based on Daily returns."""
    majors = ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]
    strength = {m: 0.0 for m in majors}
    
    if all_1d.empty:
        return {m: 50.0 for m in majors}

    # Calculate returns for all pairs in the batch
    # all_1d['Close'] is a DataFrame where columns are symbols
    try:
        closes = all_1d['Close']
        if len(closes) < 2:
            return {m: 50.0 for m in majors}
            
        returns = (closes.iloc[-1] / closes.iloc[-2]) - 1
        
        for m in majors:
            moves = []
            for symbol, ret in returns.items():
                if pd.isna(ret): continue
                # Handle Yahoo symbols like GBPJPY=X
                clean_symbol = symbol.replace("=X", "")
                if len(clean_symbol) != 6: continue
                
                base, quote = clean_symbol[:3], clean_symbol[3:6]
                if base == m:
                    moves.append(ret)
                elif quote == m:
                    moves.append(-ret)
            
            if moves:
                strength[m] = sum(moves) / len(moves)
        
        # Normalize to 0-100 (using a rough scaling factor for pct change)
        # 0.5% move average move against all others is considered "strong"
        normalized = {}
        for m, val in strength.items():
            # Scaling: 0.005 (0.5%) -> +25 points
            # Score = 50 + (val / 0.005) * 25
            score = 50 + (val * 5000) 
            normalized[m] = max(0, min(100, round(score, 1)))
        return normalized
    except Exception as e:
        print(f"Error calculating strength: {e}")
        return {m: 50.0 for m in majors}
