
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta
import os
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class InstitutionalBacktester:
    def __init__(self, symbols, start_date='2020-01-01', interval='1d'):
        self.symbols = symbols
        self.start_date = start_date
        self.interval = interval
        self.macro_symbols = {
            'DXY': 'DX-Y.NYB',
            'VIX': '^VIX',
            'US10Y': '^TNX',
            'Gold': 'GC=F',
            'SP500': '^GSPC'
        }
        self.data = {}
        self.macro_data = {}
        self.results = {}

    def fetch_data(self):
        logging.info(f"Fetching historical data for {len(self.symbols)} symbols...")
        # Download in batches to avoid rate limits
        for symbol in self.symbols:
            try:
                df = yf.download(symbol, start=self.start_date, interval=self.interval, progress=False)
                if not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    self.data[symbol] = df
                else:
                    logging.warning(f"No data for {symbol}")
            except Exception as e:
                logging.error(f"Error fetching {symbol}: {e}")

        logging.info("Fetching macro data...")
        for name, symbol in self.macro_symbols.items():
            try:
                df = yf.download(symbol, start=self.start_date, interval=self.interval, progress=False)
                if not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    self.macro_data[name] = df
            except Exception as e:
                logging.error(f"Error fetching macro {name}: {e}")

    def run_backtest(self):
        logging.info("Starting institutional stress test simulation...")
        
        # Initialize macro_trends as empty
        macro_trends = pd.DataFrame()
        
        for name, df in self.macro_data.items():
            # Calculate 20-day trend
            trend = pd.Series(np.where(df['Close'] > df['Close'].rolling(20).mean(), 'bullish', 'bearish'), index=df.index)
            ret = df['Close'].pct_change()
            
            temp_df = pd.DataFrame({
                f'{name}_trend': trend,
                f'{name}_ret': ret
            }, index=df.index)
            
            if macro_trends.empty:
                macro_trends = temp_df
            else:
                macro_trends = macro_trends.join(temp_df, how='outer')

        overall_stats = []

        for symbol in self.symbols:
            if symbol not in self.data: continue
            df = self.data[symbol].copy()
            if df.empty: continue
            
            # Align macro trends
            df = df.join(macro_trends, how='inner')
            
            # Technical Indicators (Daily level)
            df['ema20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['ema200'] = df['Close'].ewm(span=200, adjust=False).mean()
            df['trend'] = np.where(df['Close'] > df['ema20'], 'bullish', 'bearish')
            df['htf_trend'] = np.where(df['Close'] > df['ema200'], 'bullish', 'bearish')
            
            # Simulated Scorer (Macro focused)
            df['score'] = 0.0
            df.loc[df['trend'] == 'bullish', 'score'] += 1.5
            df.loc[df['htf_trend'] == 'bullish', 'score'] += 1.5
            
            # Macro Alignment
            if any(x in symbol for x in ['EUR', 'GBP', 'AUD', 'NZD']):
                # These are 'Risk-On' vs USD
                df.loc[df['DXY_trend'] == 'bearish', 'score'] += 2.0
                df.loc[df['VIX_trend'] == 'bearish', 'score'] += 2.0
                df.loc[df['SP500_trend'] == 'bullish', 'score'] += 1.0
            elif any(x in symbol for x in ['JPY', 'CHF']):
                # Safe Havens - They rise when VIX rises (but we score for the pair)
                # USDJPY rises when USD is strong or JPY is weak (Risk-On)
                if symbol.startswith('USD'):
                    df.loc[df['DXY_trend'] == 'bullish', 'score'] += 2.0
                    df.loc[df['VIX_trend'] == 'bearish', 'score'] += 2.0
                    df.loc[df['US10Y_trend'] == 'bullish', 'score'] += 1.0
            
            # Normalize score to 0-10 (Max possible is around 8-9)
            df['score'] = (df['score'] / 8.0) * 10
            df['buy_signal'] = np.where(df['score'] >= 7.5, 1, 0) # Lower threshold for daily macro
            
            # Short Score
            df['short_score'] = 0.0
            df.loc[df['trend'] == 'bearish', 'short_score'] += 1.5
            df.loc[df['htf_trend'] == 'bearish', 'short_score'] += 1.5
            if any(x in symbol for x in ['EUR', 'GBP', 'AUD', 'NZD']):
                df.loc[df['DXY_trend'] == 'bullish', 'short_score'] += 2.0
                df.loc[df['VIX_trend'] == 'bullish', 'short_score'] += 2.0
                df.loc[df['SP500_trend'] == 'bearish', 'short_score'] += 1.0
            elif any(x in symbol for x in ['JPY', 'CHF']):
                if symbol.startswith('USD'):
                    df.loc[df['DXY_trend'] == 'bearish', 'short_score'] += 2.0
                    df.loc[df['VIX_trend'] == 'bullish', 'short_score'] += 2.0
                    df.loc[df['US10Y_trend'] == 'bearish', 'short_score'] += 1.0
            
            df['short_score'] = (df['short_score'] / 8.0) * 10
            df['sell_signal'] = np.where(df['short_score'] >= 7.5, 1, 0)
            
            # Simulate Trades
            # Entry on Close of signal day, Exit after 5 days or 2 ATR move
            df['atr'] = (df['High'] - df['Low']).rolling(14).mean()
            
            trades = []
            in_position = False
            pos_type = None # 'long' or 'short'
            entry_price = 0
            entry_date = None
            stop_loss = 0
            take_profit = 0
            
            for i in range(len(df)):
                row = df.iloc[i]
                if not in_position:
                    if row['buy_signal'] == 1:
                        in_position = True
                        pos_type = 'long'
                        entry_price = row['Close']
                        entry_date = df.index[i]
                        stop_loss = entry_price - (1.5 * row['atr'])
                        take_profit = entry_price + (3.0 * row['atr']) # 3R target
                    elif row['sell_signal'] == 1:
                        in_position = True
                        pos_type = 'short'
                        entry_price = row['Close']
                        entry_date = df.index[i]
                        stop_loss = entry_price + (1.5 * row['atr'])
                        take_profit = entry_price - (3.0 * row['atr'])
                else:
                    # Check SL/TP
                    if pos_type == 'long':
                        if row['Low'] <= stop_loss:
                            trades.append({'symbol': symbol, 'entry': entry_date, 'exit': df.index[i], 'pnl': -0.02})
                            in_position = False
                        elif row['High'] >= take_profit:
                            trades.append({'symbol': symbol, 'entry': entry_date, 'exit': df.index[i], 'pnl': 0.06})
                            in_position = False
                        elif (df.index[i] - entry_date).days > 7: # Time exit
                            pnl = (row['Close'] - entry_price) / (entry_price - stop_loss) * 0.02
                            trades.append({'symbol': symbol, 'entry': entry_date, 'exit': df.index[i], 'pnl': max(-0.02, min(0.06, pnl))})
                            in_position = False
                    else: # short
                        if row['High'] <= stop_loss if stop_loss < entry_price else row['High'] >= stop_loss:
                             # Wait, stop loss for short is ABOVE entry.
                             if row['High'] >= stop_loss:
                                trades.append({'symbol': symbol, 'entry': entry_date, 'exit': df.index[i], 'pnl': -0.02})
                                in_position = False
                             elif row['Low'] <= take_profit:
                                trades.append({'symbol': symbol, 'entry': entry_date, 'exit': df.index[i], 'pnl': 0.06})
                                in_position = False
                             elif (df.index[i] - entry_date).days > 7:
                                pnl = (entry_price - row['Close']) / (stop_loss - entry_price) * 0.02
                                trades.append({'symbol': symbol, 'entry': entry_date, 'exit': df.index[i], 'pnl': max(-0.02, min(0.06, pnl))})
                                in_position = False
            
            if trades:
                tdf = pd.DataFrame(trades)
                tdf['year'] = tdf['entry'].dt.year
                
                for year, ydf in tdf.groupby('year'):
                    win_rate = len(ydf[ydf['pnl'] > 0]) / len(ydf)
                    total_pnl = ydf['pnl'].sum()
                    profit_factor = abs(ydf[ydf['pnl'] > 0]['pnl'].sum() / ydf[ydf['pnl'] < 0]['pnl'].sum()) if len(ydf[ydf['pnl'] < 0]) > 0 else 5.0
                    
                    # Max Drawdown
                    ydf['cum_pnl'] = (1 + ydf['pnl']).cumprod()
                    drawdown = (ydf['cum_pnl'].cummax() - ydf['cum_pnl']) / ydf['cum_pnl'].cummax()
                    max_dd = drawdown.max()

                    overall_stats.append({
                        'symbol': symbol,
                        'year': int(year),
                        'trades': len(ydf),
                        'win_rate': win_rate,
                        'total_pnl_pct': total_pnl * 100,
                        'profit_factor': profit_factor,
                        'max_dd_pct': max_dd * 100
                    })

        return pd.DataFrame(overall_stats)

if __name__ == "__main__":
    from config import SYMBOLS
    bt = InstitutionalBacktester(SYMBOLS, start_date='2020-01-01', interval='1d')
    bt.fetch_data()
    results = bt.run_backtest()
    print("\n--- 6-Year Macro Stress Test Results ---")
    print(results.to_string())
    print(f"\nAverage Win Rate: {results['win_rate'].mean():.2%}")
    print(f"Average Profit Factor: {results['profit_factor'].mean():.2f}")
    
    # Save results
    results.to_json("/home/team/shared/aurum_edge_v1/stress_test_results.json", orient='records', indent=4)
