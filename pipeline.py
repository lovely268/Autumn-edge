import yfinance as yf
import pandas as pd
from datetime import datetime, timezone
import config
from scorer import InstitutionalScorer
from futures_strategy_engine import FuturesStrategyEngine

class DataPipeline:
    def __init__(self, symbol=config.SYMBOL):
        self.symbol = symbol
        self.dxy_symbol = "DX-Y.NYB"
        self.sp500_symbol = "^GSPC"
        self.tnx_symbol = "^TNX" # US 10Y Yield (Macro Sentiment)
        self.data = pd.DataFrame() # 5m data
        self.mtf_data = pd.DataFrame() # 15m data
        self.dxy_data = pd.DataFrame()
        self.sp500_data = pd.DataFrame()
        self.tnx_data = pd.DataFrame()
        self.htf_data = pd.DataFrame() # 1h data
        self.conf_data = pd.DataFrame() # 1m data
        self.daily_data = pd.DataFrame() # Daily data
        self.weekly_data = pd.DataFrame() # Weekly data
        self.scorer = InstitutionalScorer()
        self.futures_engine = FuturesStrategyEngine()
        self.order_flow_data = {}
        self.session_boundaries = {
            'asian': {'high': None, 'low': None, 'date': None},
            'london': {'high': None, 'low': None, 'date': None},
            'ny': {'high': None, 'low': None, 'date': None},
            'pd': {'high': None, 'low': None, 'date': None} # Previous Day
        }

    def fetch_latest_data(self, period="5d", pre_fetched=None):
        """Fetches the latest data or uses pre-fetched batch data."""
        if pre_fetched:
            self.data = pre_fetched.get('5m', pd.DataFrame())
            self.mtf_data = pre_fetched.get('15m', pd.DataFrame())
            self.htf_data = pre_fetched.get('1h', pd.DataFrame())
            self.conf_data = pre_fetched.get('1m', pd.DataFrame())
            self.daily_data = pre_fetched.get('1d', pd.DataFrame())
            self.weekly_data = pre_fetched.get('1wk', pd.DataFrame())
            return self.data

        print(f"Fetching data for {self.symbol}...")

        def safe_download(symbol, period, interval):
            try:
                df = yf.download(symbol, period=period, interval=interval, progress=False)
                if not df.empty:
                    # Flatten MultiIndex if present
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    df.index = df.index.tz_convert('UTC')
                return df
            except Exception as e:
                print(f"Error downloading {symbol}: {e}")
                return pd.DataFrame()

        # Symbol-specific data
        self.data = safe_download(self.symbol, period, config.INTERVAL)
        self.mtf_data = safe_download(self.symbol, period, config.MTF_INTERVAL)
        self.htf_data = safe_download(self.symbol, period, config.HTF_INTERVAL)
        self.conf_data = safe_download(self.symbol, "2d", config.CONFIRMATION_INTERVAL)

        return self.data

    def set_macro_data(self, dxy, sp500, tnx, yields):
        """Sets global macro data to avoid redundant downloads."""
        self.dxy_data = dxy
        self.sp500_data = sp500
        self.tnx_data = tnx
        self.yields = yields # Dictionary of yield DataFrames

    def set_order_flow_data(self, order_flow):
        """Sets Layer 9 order flow data (Net Volume Delta, Position Ratios)."""
        self.order_flow_data = order_flow

    def update_session_boundaries(self):
        """Identifies highs and lows for sessions using 5m data."""
        if self.data.empty:
            return

        df = self.data.copy()
        df['hour'] = df.index.hour
        df['date'] = df.index.date

        latest_date = df['date'].max()
        
        # Asian session (Current Day)
        asian_data = df[(df['date'] == latest_date) & 
                        (df['hour'] >= config.ASIAN_SESSION_START) & 
                        (df['hour'] < config.ASIAN_SESSION_END)]
        if not asian_data.empty:
            self.session_boundaries['asian']['high'] = float(asian_data['High'].max())
            self.session_boundaries['asian']['low'] = float(asian_data['Low'].min())
            self.session_boundaries['asian']['date'] = str(latest_date)
            
        # London session (Current Day)
        london_data = df[(df['date'] == latest_date) & 
                         (df['hour'] >= config.LONDON_SESSION_START) & 
                         (df['hour'] < config.LONDON_SESSION_END)]
        if not london_data.empty:
            self.session_boundaries['london']['high'] = float(london_data['High'].max())
            self.session_boundaries['london']['low'] = float(london_data['Low'].min())
            self.session_boundaries['london']['date'] = str(latest_date)

        # NY session (Current Day)
        ny_data = df[(df['date'] == latest_date) & 
                     (df['hour'] >= config.NY_SESSION_START) & 
                     (df['hour'] < config.NY_SESSION_END)]
        if not ny_data.empty:
            self.session_boundaries['ny']['high'] = float(ny_data['High'].max())
            self.session_boundaries['ny']['low'] = float(ny_data['Low'].min())
            self.session_boundaries['ny']['date'] = str(latest_date)

        # Previous Day High/Low
        unique_dates = sorted(df['date'].unique())
        if len(unique_dates) >= 2:
            prev_date = unique_dates[-2]
            prev_day_data = df[df['date'] == prev_date]
            self.session_boundaries['pd']['high'] = float(prev_day_data['High'].max())
            self.session_boundaries['pd']['low'] = float(prev_day_data['Low'].min())
            self.session_boundaries['pd']['date'] = str(prev_date)

    def get_current_state(self, macro_filters=None, cb_sentiment=0.0, economic_surprise=0.0, order_book=None):
        """Returns the current market state and session boundaries."""
        if self.data.empty:
            return None
            
        latest_price = float(self.data['Close'].iloc[-1])
        
        # 1. Calculate ATR (14-period)
        df = self.data.copy()
        df['h-l'] = df['High'] - df['Low']
        df['h-pc'] = abs(df['High'] - df['Close'].shift(1))
        df['l-pc'] = abs(df['Low'] - df['Close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        df['atr'] = df['tr'].rolling(14).mean()
        
        latest_atr = float(df['atr'].iloc[-1]) if not df['atr'].empty and not pd.isna(df['atr'].iloc[-1]) else 0.1
        
        # 2. Yield Divergence (Dynamic based on symbol)
        yield_spread = 0.0
        try:
            # Pair-to-Yield Mapping
            yield_map = {
                'GBPJPY=X': ('UK', 'JP'),
                'GBPUSD=X': ('UK', 'US'),
                'USDJPY=X': ('US', 'JP'),
                'EURUSD=X': ('GE', 'US')
            }
            
            p1, p2 = yield_map.get(self.symbol, (None, None))
            y1_df = self.yields.get(p1, pd.DataFrame()) if p1 else pd.DataFrame()
            y2_df = self.yields.get(p2, pd.DataFrame()) if p2 else pd.DataFrame()

            if not y1_df.empty and not y2_df.empty:
                y1_val = float(y1_df['Close'].iloc[-1])
                y1_prev = float(y1_df['Close'].iloc[-2]) if len(y1_df) > 1 else y1_val
                y2_val = float(y2_df['Close'].iloc[-1])
                y2_prev = float(y2_df['Close'].iloc[-2]) if len(y2_df) > 1 else y2_val
                yield_spread = (y1_val - y1_prev) - (y2_val - y2_prev)
            else:
                # Fallback to relative currency strength
                if not self.data.empty and len(self.data) > 1:
                    df_close = self.data['Close']
                    yield_spread = (df_close.iloc[-1] / df_close.iloc[-2]) - 1
        except Exception as e:
            pass

        # 3. Multi-Timeframe Trend Analysis (Recursive Fractal Alignment)
        conf_trend = "neutral"
        htf_trend = "neutral"
        mtf_trend = "neutral"
        daily_trend = "neutral"
        weekly_trend = "neutral"

        if not self.conf_data.empty:
            self.conf_data['ema'] = self.conf_data['Close'].ewm(span=20, adjust=False).mean()
            conf_price = float(self.conf_data['Close'].iloc[-1])
            conf_ema = float(self.conf_data['ema'].iloc[-1])
            conf_trend = "bullish" if conf_price > conf_ema else "bearish"

        if not self.htf_data.empty:
            self.htf_data['ema'] = self.htf_data['Close'].ewm(span=config.HTF_EMA_PERIOD, adjust=False).mean()
            htf_price = float(self.htf_data['Close'].iloc[-1])
            htf_ema = float(self.htf_data['ema'].iloc[-1])
            htf_trend = "bullish" if htf_price > htf_ema else "bearish"

        if not self.mtf_data.empty:
            self.mtf_data['ema'] = self.mtf_data['Close'].ewm(span=20, adjust=False).mean()
            mtf_price = float(self.mtf_data['Close'].iloc[-1])
            mtf_ema = float(self.mtf_data['ema'].iloc[-1])
            mtf_trend = "bullish" if mtf_price > mtf_ema else "bearish"

        if not self.daily_data.empty:
            self.daily_data['ema'] = self.daily_data['Close'].ewm(span=50, adjust=False).mean()
            d_price = float(self.daily_data['Close'].iloc[-1])
            d_ema = float(self.daily_data['ema'].iloc[-1])
            daily_trend = "bullish" if d_price > d_ema else "bearish"

        if not self.weekly_data.empty:
            self.weekly_data['ema'] = self.weekly_data['Close'].ewm(span=20, adjust=False).mean()
            w_price = float(self.weekly_data['Close'].iloc[-1])
            w_ema = float(self.weekly_data['ema'].iloc[-1])
            weekly_trend = "bullish" if w_price > w_ema else "bearish"

        # 4. Retail Sentiment Filter
        retail_sentiment = "neutral"
        if htf_trend == "bullish" and daily_trend == "bullish" and yield_spread > 0:
            retail_sentiment = "short" 
        elif htf_trend == "bearish" and daily_trend == "bearish" and yield_spread < 0:
            retail_sentiment = "long"  

        # 5. ML Probability Scorer (Generic calculation for monitoring)
        indicators = macro_filters.get('indicators', {}) if macro_filters else {}
        narratives = macro_filters.get('narratives', {}) if macro_filters else {}
        
        market_state_for_scoring = {
            'conf_trend': conf_trend,
            'htf_trend': htf_trend,
            'mtf_trend': mtf_trend,
            'daily_trend': daily_trend,
            'weekly_trend': weekly_trend,
            'yield_spread_momentum': yield_spread, # Renamed for clarity in scorer
            'macro_dxy_trend': indicators.get('DXY', {}).get('trend', 'neutral'),
            'macro_vix_trend': indicators.get('VIX', {}).get('trend', 'neutral'),
            'macro_gold_trend': indicators.get('Gold', {}).get('trend', 'neutral'),
            'cb_sentiment_score': cb_sentiment,
            'economic_surprise': economic_surprise,
            'retail_sentiment': retail_sentiment,
            'net_volume_delta': self.order_flow_data.get('net_volume_delta', 0),
            'long_pos': self.order_flow_data.get('long_pos', 50),
            'short_pos': self.order_flow_data.get('short_pos', 50),
            'narratives': narratives
        }
        
        # Calculate generic scores for long/short
        long_calc = self.scorer.calculate_score(self.symbol, "long", market_state_for_scoring)
        short_calc = self.scorer.calculate_score(self.symbol, "short", market_state_for_scoring)
        
        # Determine current primary bias
        primary_score = long_calc['score'] if long_calc['score'] >= short_calc['score'] else short_calc['score']
        
        # 5.5 Dynamic Liquidity Gating (Layer 13)
        long_liquidity_gated = False
        short_liquidity_gated = False
        if order_book:
            buckets = order_book.get('buckets', [])
            cp = float(order_book.get('price', latest_price))
            pip = 0.01 if "JPY" in self.symbol else 0.0001
            
            for b in buckets:
                price = float(b['price'])
                # Cluster within 12 pips
                if abs(price - cp) < 12 * pip:
                    # Sell Stops (Short orders below price)
                    if price < cp and float(b.get('shortCountPercent', 0)) > 2.0:
                        long_liquidity_gated = True
                    # Buy Stops (Long orders above price)
                    if price > cp and float(b.get('longCountPercent', 0)) > 2.0:
                        short_liquidity_gated = True

        # 6. Sniper Entry Detection (FVG & OB)
        latest_fvg = None
        latest_ob = None
        if not self.conf_data.empty and len(self.conf_data) >= 5:
            cdf = self.conf_data.tail(10).copy()
            for i in range(2, len(cdf)):
                c1, c3 = cdf.iloc[i-2], cdf.iloc[i]
                if c3['Low'] > c1['High']:
                    latest_fvg = {'type': 'bullish', 'top': float(c3['Low']), 'bottom': float(c1['High']), 'mean': float((c3['Low'] + c1['High']) / 2)}
                    for j in range(i-1, 0, -1):
                        cand = cdf.iloc[j]
                        if cand['Close'] < cand['Open']:
                            latest_ob = {'type': 'bullish', 'high': float(cand['High']), 'low': float(cand['Low']), 'mean': float((cand['High'] + cand['Low']) / 2)}
                            break
                elif c3['High'] < c1['Low']:
                    latest_fvg = {'type': 'bearish', 'top': float(c1['Low']), 'bottom': float(c3['High']), 'mean': float((c1['Low'] + c3['High']) / 2)}
                    for j in range(i-1, 0, -1):
                        cand = cdf.iloc[j]
                        if cand['Close'] > cand['Open']:
                            latest_ob = {'type': 'bearish', 'high': float(cand['High']), 'low': float(cand['Low']), 'mean': float((cand['High'] + cand['Low']) / 2)}
                            break

        # 7. Futures Strategy Engine (Step Sequence)
        futures_setup = None
        if "=F" in self.symbol:
            market_data = {
                '1m': self.conf_data,
                '5m': self.data,
                '15m': self.mtf_data,
                '1d': self.daily_data
            }
            futures_setup = self.futures_engine.process_symbol(self.symbol, market_data)

        return {
            'symbol': self.symbol,
            'latest_price': latest_price,
            'latest_atr': latest_atr,
            'ml_score': primary_score,
            'long_score': long_calc['score'],
            'short_score': short_calc['score'],
            'is_long_gated': long_calc['is_hard_gated'] or long_liquidity_gated,
            'is_short_gated': short_calc['is_hard_gated'] or short_liquidity_gated,
            'long_liquidity_gated': long_liquidity_gated,
            'short_liquidity_gated': short_liquidity_gated,
            'gate_failures': (long_calc['gate_failures'] + (["Liquidity Gated (SL Cluster Below)"] if long_liquidity_gated else [])) if primary_score == long_calc['score'] else (short_calc['gate_failures'] + (["Liquidity Gated (SL Cluster Above)"] if short_liquidity_gated else [])),
            'scoring_state': market_state_for_scoring, # Pass the raw state for re-calculation
            'htf_trend': htf_trend,
            'mtf_trend': mtf_trend,
            'daily_trend': daily_trend,
            'weekly_trend': weekly_trend,
            'latest_fvg': latest_fvg,
            'latest_ob': latest_ob,
            'futures_setup': futures_setup,
            'futures_active_step': self.futures_engine.active_setups.get(self.symbol, {}).get('step'),
            'macro_regime': macro_filters.get('regime', 'neutral') if macro_filters else 'neutral',
            'session_boundaries': self.session_boundaries,
            'timestamp': self.data.index[-1].isoformat()
        }
