import time
import json
import os
import pandas as pd
from oanda_execution import OandaExecution
from pipeline import DataPipeline
from macro_alpha import MacroAlpha
import config
from datetime import datetime, timedelta, timezone
from utils import fetch_economic_calendar, check_news_blackout, generate_weekly_report, update_daily_stats, perform_sunday_refresh, calculate_currency_strength, sanitize_nans

STATE_FILE = config.STATE_FILE

def fetch_global_macro():
    import yfinance as yf
    def safe_download(symbol, period="5d", interval="5m"):
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                df.index = df.index.tz_localize('UTC') if df.index.tz is None else df.index.tz_convert('UTC')
            return df
        except: return pd.DataFrame()
    return safe_download("DX-Y.NYB"), safe_download("^GSPC"), safe_download("^TNX"), {
        'US': safe_download("^TNX"), 'UK': safe_download("^GUK10"), 'JP': safe_download("^GJGB10"), 'GE': safe_download("^GDBR10")
    }

def fetch_futures_data():
    import yfinance as yf
    futures_symbols = ["ES=F", "NQ=F", "CL=F", "GC=F", "6E=F", "6B=F", "6J=F", "6A=F", "6N=F", "6C=F", "6S=F"]
    try:
        data = yf.download(futures_symbols, period="2d", interval="5m", progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            return data
        return pd.DataFrame()
    except:
        return pd.DataFrame()

def get_oanda_sentiment(instrument):
    if "=F" in instrument: return 50.0, 50.0 # Sentiment not available for Futures yet
    import oandapyV20
    import oandapyV20.endpoints.instruments as instruments
    api_key = config.OANDA_API_KEY
    if not api_key: return 50.0, 50.0
    client = oandapyV20.API(access_token=api_key, environment=config.OANDA_ENVIRONMENT)
    try:
        oanda_symbol = instrument.replace("=X", "").replace("/", "_")
        if len(oanda_symbol) == 6:
            oanda_symbol = f"{oanda_symbol[:3]}_{oanda_symbol[3:]}"
            
        r = instruments.InstrumentsPositionBook(instrument=oanda_symbol)
        client.request(r)
        book = r.response.get('positionBook')
        if book:
            return float(book.get('longPercent', 50)), float(book.get('shortPercent', 50))
    except: pass
    return 50.0, 50.0

def calculate_volume_delta(futures_data, symbol):
    mapping = {
        "EURUSD=X": "6E=F", "GBPUSD=X": "6B=F", "USDJPY=X": "6J=F",
        "AUDUSD=X": "6A=F", "NZDUSD=X": "6N=F", "USDCAD=X": "6C=F",
        "USDCHF=X": "6S=F", "GC=F": "GC=F", "ES=F": "ES=F", "NQ=F": "NQ=F",
        "CL=F": "CL=F"
    }
    fut_symbol = mapping.get(symbol)
    if not fut_symbol:
        if "=F" in symbol: fut_symbol = symbol # Direct futures symbol
        else: return 0.0
    
    if fut_symbol not in futures_data.columns.get_level_values(1):
        return 0.0
    
    try:
        df = futures_data.xs(fut_symbol, axis=1, level=1).tail(5)
        delta = 0.0
        for _, row in df.iterrows():
            rng = (row['High'] - row['Low'])
            if rng > 0:
                delta += ((row['Close'] - row['Open']) / rng) * row['Volume']
        return round(delta, 2)
    except:
        return 0.0

def run_pipeline_service():
    symbols = getattr(config, 'SYMBOLS', [config.SYMBOL])
    pipelines = {s: DataPipeline(symbol=s) for s in symbols}
    ma = MacroAlpha()
    executor = OandaExecution() if config.LIVE_MODE else None
    print(f"Aurum Edge Pipeline Service (Hardened - Phase 4) starting...")
    
    last_calendar_fetch = None
    last_daily_refresh = None
    last_weekly_report = None
    economic_calendar = []

    while True:
        try:
            now = datetime.now(timezone.utc)
            
            # 1. Hourly Calendar Fetch
            if last_calendar_fetch is None or (now - last_calendar_fetch).total_seconds() > 3600:
                economic_calendar = fetch_economic_calendar()
                last_calendar_fetch = now
                print("Economic calendar refreshed.")

            # 2. Daily Refresh
            if now.hour == 6 and now.minute >= 30 and (last_daily_refresh is None or last_daily_refresh.date() != now.date()):
                update_daily_stats()
                last_daily_refresh = now

            # 3. Sunday Refresh
            if now.weekday() == 6 and now.hour == 22 and (last_weekly_report is None or last_weekly_report.date() != now.date()):
                perform_sunday_refresh()
                last_weekly_report = now

            # 4. News Blackout Check
            news_active = check_news_blackout(economic_calendar)

            # 5. Macro Alpha Filters (New in Phase 4)
            macro_filters = ma.calculate_macro_filters()
            scored_speeches = ma.score_latest_speeches()
            avg_sentiment = 0.0
            if scored_speeches:
                avg_sentiment = sum(s['sentiment_score'] for s in scored_speeches) / len(scored_speeches)
            
            # Load economic deviations from scraper service
            economic_surprise = 0.0
            DEVIATION_FILE = "/home/team/shared/aurum_edge_v1/economic_deviations.json"
            if os.path.exists(DEVIATION_FILE):
                try:
                    with open(DEVIATION_FILE, "r") as f:
                        dev_data = json.load(f)
                        # Example: get the deviation for the symbol's base currency if USD
                        # This is a simplification; a real engine would match the symbol
                        economic_surprise = dev_data.get("USD", {}).get("deviation", 0.0)
                except: pass

            # 6. Data Fetching & Processing
            dxy, sp500, tnx, yields = fetch_global_macro()
            futures_data = fetch_futures_data()
            
            import yfinance as yf
            all_1m = yf.download(symbols, period="2d", interval=config.CONFIRMATION_INTERVAL, progress=False)
            all_5m = yf.download(symbols, period="5d", interval=config.INTERVAL, progress=False)
            all_15m = yf.download(symbols, period="5d", interval=config.MTF_INTERVAL, progress=False)
            all_1h = yf.download(symbols, period="5d", interval=config.HTF_INTERVAL, progress=False)
            all_1d = yf.download(symbols, period="1mo", interval="1d", progress=False)
            all_1wk = yf.download(symbols, period="6mo", interval="1wk", progress=False)
            
            currency_strength = calculate_currency_strength(all_1d)

            master_state = {}
            for symbol in symbols:
                try:
                    pipeline = pipelines[symbol]
                    pre_fetched = {}
                    try:
                        if not all_5m.empty: pre_fetched['5m'] = all_5m.xs(symbol, axis=1, level=1)
                        if not all_15m.empty: pre_fetched['15m'] = all_15m.xs(symbol, axis=1, level=1)
                        if not all_1h.empty: pre_fetched['1h'] = all_1h.xs(symbol, axis=1, level=1)
                        if not all_1m.empty: pre_fetched['1m'] = all_1m.xs(symbol, axis=1, level=1)
                        if not all_1d.empty: pre_fetched['1d'] = all_1d.xs(symbol, axis=1, level=1)
                        if not all_1wk.empty: pre_fetched['1wk'] = all_1wk.xs(symbol, axis=1, level=1)
                    except: pass

                    pipeline.fetch_latest_data(pre_fetched=pre_fetched if pre_fetched else None)
                    pipeline.set_macro_data(dxy, sp500, tnx, yields)
                    
                    long_p, short_p = get_oanda_sentiment(symbol)
                    net_vol = calculate_volume_delta(futures_data, symbol)
                    pipeline.set_order_flow_data({
                        'long_pos': long_p,
                        'short_pos': short_p,
                        'net_volume_delta': net_vol
                    })

                    pipeline.update_session_boundaries()
                    
                    # 6.5 Dynamic Liquidity Heatmap (Layer 13)
                    order_book = None
                    if executor and (symbol in config.TIER_1 or symbol in config.TIER_2):
                        oanda_symbol = symbol.replace("=X", "").replace("USDJPY", "USD_JPY").replace("EURUSD", "EUR_USD").replace("GBPUSD", "GBP_USD")
                        if "_" not in oanda_symbol and len(oanda_symbol) == 6:
                            oanda_symbol = f"{oanda_symbol[:3]}_{oanda_symbol[3:]}"
                        order_book = executor.get_order_book(oanda_symbol)

                    # Pass Macro Alpha data including surprise
                    state = pipeline.get_current_state(
                        macro_filters=macro_filters, 
                        cb_sentiment=avg_sentiment,
                        economic_surprise=economic_surprise,
                        order_book=order_book
                    )
                    if state:
                        state['news_active'] = news_active
                        master_state[symbol] = state
                except Exception as e:
                    print(f"Error processing {symbol}: {e}")
                    continue

            if master_state:
                master_state['_global'] = {
                    'currency_strength': currency_strength,
                    'macro_regime': macro_filters.get('regime', 'neutral'),
                    'avg_cb_sentiment': avg_sentiment,
                    'timestamp': now.isoformat()
                }
                
                sanitized_state = sanitize_nans(master_state)
                master_state_json = json.dumps(sanitized_state, indent=4, allow_nan=False)
                
                temp_state = STATE_FILE + ".tmp"
                with open(temp_state, "w") as f:
                    f.write(master_state_json)
                os.replace(temp_state, STATE_FILE)
                
                try:
                    highs = [f"{s}({master_state[s].get('ml_score', 0)})" for s in master_state if s != '_global' and isinstance(master_state[s], dict) and master_state[s].get('ml_score', 0) >= 8]
                    print(f"[{now.strftime('%H:%M:%S')}] Scanned {len(master_state)-1} symbols. AAA: {', '.join(highs[:3])}")
                except: pass

            time.sleep(60) 
        except Exception as e:
            print(f"Error: {e}"); time.sleep(60)

if __name__ == "__main__":
    run_pipeline_service()
