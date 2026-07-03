import yfinance as yf
import pandas as pd
import numpy as np
import config

def fetch_data(symbol, interval, period):
    print(f"Fetching {interval} data for {symbol} ({period})...")
    data = yf.download(symbol, period=period, interval=interval)
    if data.empty:
        return data
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data.index = data.index.tz_convert('UTC')
    return data

def run_backtest(df, rr, disp_mult, compounding=True):
    df = df.copy()
    df['hour'] = df.index.hour
    df['date'] = df.index.date
    df['body_size'] = abs(df['Close'] - df['Open'])
    df['avg_body'] = df['body_size'].rolling(20).mean()
    
    # 1. Asian Session (00:00 - 06:00 UTC)
    asian_session = df[(df['hour'] >= 0) & (df['hour'] < 6)]
    asian_high = asian_session.groupby('date')['High'].max()
    asian_low = asian_session.groupby('date')['Low'].min()
    
    # 2. London Session (07:00 - 12:00 UTC)
    london_session = df[(df['hour'] >= 7) & (df['hour'] < 12)]
    london_high = london_session.groupby('date')['High'].max()
    london_low = london_session.groupby('date')['Low'].min()
    
    # 3. Previous Day H/L
    # Calculate daily H/L
    daily_data = df.resample('D').agg({'High': 'max', 'Low': 'min'})
    prev_day_high = daily_data['High'].shift(1)
    prev_day_low = daily_data['Low'].shift(1)
    
    df['asian_high'] = df['date'].map(asian_high)
    df['asian_low'] = df['date'].map(asian_low)
    df['london_high'] = df['date'].map(london_high)
    df['london_low'] = df['date'].map(london_low)
    df['pd_high'] = df['date'].map(prev_day_high)
    df['pd_low'] = df['date'].map(prev_day_low)
    
    trades = []
    active_trade = None
    balance = 100.0
    risk_pct = 0.05 # Use 5% for very aggressive growth
    
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    opens = df['Open'].values
    hours = df['hour'].values
    a_highs = df['asian_high'].values
    a_lows = df['asian_low'].values
    l_highs = df['london_high'].values
    l_lows = df['london_low'].values
    pd_highs = df['pd_high'].values
    pd_lows = df['pd_low'].values
    body_sizes = df['body_size'].values
    avg_bodies = df['avg_body'].values
    times = df.index
    
    for i in range(1, len(df)):
        if active_trade:
            if active_trade['type'] == 'short':
                if highs[i] >= active_trade['stop_loss']:
                    profit = active_trade['size'] * (active_trade['entry_price'] - active_trade['stop_loss'])
                    balance += profit
                    trades.append({'result': -1, 'profit': profit, 'balance': balance, 'setup': active_trade['setup']})
                    active_trade = None
                elif lows[i] <= active_trade['take_profit']:
                    profit = active_trade['size'] * (active_trade['entry_price'] - active_trade['take_profit'])
                    balance += profit
                    trades.append({'result': rr, 'profit': profit, 'balance': balance, 'setup': active_trade['setup']})
                    active_trade = None
            else: # long
                if lows[i] <= active_trade['stop_loss']:
                    profit = active_trade['size'] * (active_trade['stop_loss'] - active_trade['entry_price'])
                    balance += profit
                    trades.append({'result': -1, 'profit': profit, 'balance': balance, 'setup': active_trade['setup']})
                    active_trade = None
                elif highs[i] >= active_trade['take_profit']:
                    profit = active_trade['size'] * (active_trade['take_profit'] - active_trade['entry_price'])
                    balance += profit
                    trades.append({'result': rr, 'profit': profit, 'balance': balance, 'setup': active_trade['setup']})
                    active_trade = None
        
        if active_trade is None:
            if pd.isna(avg_bodies[i]): continue
            is_displaced = body_sizes[i] > avg_bodies[i] * disp_mult
            
            # Setup discovery
            setup = None
            entry_type = None
            
            # Entry Window: London + NY (06:00 - 20:00 UTC)
            if 6 <= hours[i] < 20:
                # 1. Asian Sweep
                if not pd.isna(a_highs[i]):
                    if highs[i-1] > a_highs[i] and closes[i] < a_highs[i] and is_displaced and closes[i] < opens[i]:
                        setup = "Asian_Sweep"
                        entry_type = "short"
                        sl_price = highs[i-1]
                    elif lows[i-1] < a_lows[i] and closes[i] > a_lows[i] and is_displaced and closes[i] > opens[i]:
                        setup = "Asian_Sweep"
                        entry_type = "long"
                        sl_price = lows[i-1]

                # 2. London Sweep (During NY)
                if not setup and 13 <= hours[i] < 20 and not pd.isna(l_highs[i]):
                    if highs[i-1] > l_highs[i] and closes[i] < l_highs[i] and is_displaced and closes[i] < opens[i]:
                        setup = "London_Sweep"
                        entry_type = "short"
                        sl_price = highs[i-1]
                    elif lows[i-1] < l_lows[i] and closes[i] > l_lows[i] and is_displaced and closes[i] > opens[i]:
                        setup = "London_Sweep"
                        entry_type = "long"
                        sl_price = lows[i-1]
                
                # 3. Prev Day Sweep
                if not setup and not pd.isna(pd_highs[i]):
                    if highs[i-1] > pd_highs[i] and closes[i] < pd_highs[i] and is_displaced and closes[i] < opens[i]:
                        setup = "PD_Sweep"
                        entry_type = "short"
                        sl_price = highs[i-1]
                    elif lows[i-1] < pd_lows[i] and closes[i] > pd_lows[i] and is_displaced and closes[i] > opens[i]:
                        setup = "PD_Sweep"
                        entry_type = "long"
                        sl_price = lows[i-1]

            if setup:
                entry_price = closes[i]
                if entry_type == "short":
                    stop_loss = sl_price + 0.3
                    risk_dist = stop_loss - entry_price
                    if risk_dist > 0.2:
                        risk_amount = balance * risk_pct if compounding else 100.0 * risk_pct
                        size = risk_amount / risk_dist
                        active_trade = {'type': 'short', 'entry_price': entry_price, 'stop_loss': stop_loss, 'take_profit': entry_price - (risk_dist * rr), 'size': size, 'setup': setup}
                else:
                    stop_loss = sl_price - 0.3
                    risk_dist = entry_price - stop_loss
                    if risk_dist > 0.2:
                        risk_amount = balance * risk_pct if compounding else 100.0 * risk_pct
                        size = risk_amount / risk_dist
                        active_trade = {'type': 'long', 'entry_price': entry_price, 'stop_loss': stop_loss, 'take_profit': entry_price + (risk_dist * rr), 'size': size, 'setup': setup}
                            
    return trades, balance

def main():
    symbol = "GC=F"
    intervals = ["15m", "5m", "1m"]
    periods = ["60d", "60d", "7d"]
    
    results = []
    
    for interval, period in zip(intervals, periods):
        data = fetch_data(symbol, interval, period)
        if data.empty:
            continue
            
        for rr in [3, 4, 5]:
            for disp in [2.0, 2.5, 3.0]:
                trades, final_balance = run_backtest(data, rr, disp, compounding=True)
                if trades:
                    win_rate = (np.array([t['result'] for t in trades]) > 0).mean()
                    results.append({
                        'interval': interval,
                        'rr': rr,
                        'disp': disp,
                        'trades': len(trades),
                        'win_rate': win_rate,
                        'final_balance': final_balance
                    })
                    print(f"Int: {interval}, RR: {rr}, Disp: {disp} -> Trades: {len(trades)}, WR: {win_rate:.2%}, Bal: ${final_balance:.2f}")
                    # setup distribution
                    setups = pd.Series([t['setup'] for t in trades]).value_counts()
                    print(f"Setups: {setups.to_dict()}")

    if results:
        best = max(results, key=lambda x: x['final_balance'])
        print("\n--- BEST SETTINGS ---")
        print(best)

if __name__ == "__main__":
    main()
