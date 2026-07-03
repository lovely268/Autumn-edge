
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import config

class FuturesStrategyEngine:
    def __init__(self):
        self.levels = {} # Symbol: {asia_h, asia_l, pdh, pdl}
        self.active_setups = {} # Symbol: {step, direction, levels, timestamp}

    def update_institutional_levels(self, symbol, data_5m, data_daily):
        """
        Step A: Mark Key Levels (Asia H/L, PDH, PDL)
        """
        if data_5m.empty or data_daily.empty:
            return None

        # Asia Range: 8:00 PM ET to 12:00 AM ET (00:00 UTC to 04:00 UTC)
        # Use 5m data to find high/low in this window
        df_5m = data_5m.copy()
        df_5m.index = pd.to_datetime(df_5m.index)
        
        # Filter for Asia session (UTC 00:00 to 04:00)
        asia_range = df_5m[(df_5m.index.hour >= 0) & (df_5m.index.hour < 4)]
        if asia_range.empty:
            asia_h, asia_l = None, None
        else:
            asia_h = float(asia_range['High'].max())
            asia_l = float(asia_range['Low'].min())

        # Previous Day High/Low
        # Previous Day is the last complete daily candle
        pdh = float(data_daily['High'].iloc[-1])
        pdl = float(data_daily['Low'].iloc[-1])

        self.levels[symbol] = {
            "asia_h": asia_h,
            "asia_l": asia_l,
            "pdh": pdh,
            "pdl": pdl
        }
        return self.levels[symbol]

    def detect_sweep(self, symbol, current_price, levels, data_15m):
        """
        Step B: Sweep Detection (15M wick beyond level)
        """
        if data_15m.empty:
            return None

        last_15m = data_15m.iloc[-1]
        
        # Check for sweeps of each level
        for level_name, level_price in levels.items():
            if level_price is None: continue
            
            # Bullish Sweep (Liquidity Grab below Low)
            if level_name in ["asia_l", "pdl"]:
                # Price moved beyond level and rejected back above
                if last_15m['Low'] < level_price and last_15m['Close'] > level_price:
                    # Wick size check: (min(open, close) - low) / (high - low) >= 0.5
                    total_size = last_15m['High'] - last_15m['Low']
                    lower_wick = min(last_15m['Open'], last_15m['Close']) - last_15m['Low']
                    if total_size > 0 and (lower_wick / total_size) >= 0.5:
                        return {"type": "bullish_sweep", "level": level_name, "price": level_price}
            
            # Bearish Sweep (Liquidity Grab above High)
            if level_name in ["asia_h", "pdh"]:
                if last_15m['High'] > level_price and last_15m['Close'] < level_price:
                    total_size = last_15m['High'] - last_15m['Low']
                    upper_wick = last_15m['High'] - max(last_15m['Open'], last_15m['Close'])
                    if total_size > 0 and (upper_wick / total_size) >= 0.5:
                        return {"type": "bearish_sweep", "level": level_name, "price": level_price}

        return None

    def detect_displacement(self, symbol, sweep_info, data_15m):
        """
        Step C: Displacement Candle (Strong 15M move away)
        """
        if data_15m.empty or len(data_15m) < 2:
            return False

        last_15m = data_15m.iloc[-1]
        prev_15m = data_15m.iloc[-2]
        
        # Displacement: Large candle in opposite direction of sweep
        body_size = abs(last_15m['Close'] - last_15m['Open'])
        avg_body = abs(data_15m['Close'] - data_15m['Open']).tail(10).mean()
        
        if sweep_info['type'] == "bullish_sweep":
            # Bullish Displacement: Green candle, body > 1.5 * average body
            if last_15m['Close'] > last_15m['Open'] and body_size > 1.5 * avg_body:
                return True
        elif sweep_info['type'] == "bearish_sweep":
            # Bearish Displacement: Red candle, body > 1.5 * average body
            if last_15m['Close'] < last_15m['Open'] and body_size > 1.5 * avg_body:
                return True
                
        return False

    def detect_mss(self, symbol, direction, data_1m_5m):
        """
        Step D: Market Structure Shift (MSS on 1M/5M)
        """
        if data_1m_5m.empty or len(data_1m_5m) < 10:
            return False

        df = data_1m_5m.copy()
        
        if direction == "long":
            # MSS Long: Price closes above recent swing high
            recent_swing_high = df['High'].iloc[-10:-1].max()
            if df['Close'].iloc[-1] > recent_swing_high:
                return True
        else:
            # MSS Short: Price closes below recent swing low
            recent_swing_low = df['Low'].iloc[-10:-1].min()
            if df['Close'].iloc[-1] < recent_swing_low:
                return True
                
        return False

    def get_fvg_ob_zone(self, symbol, direction, data_conf):
        """
        Step E: Find FVG or Order Block (50% zone limit)
        """
        # Logic similar to what's in pipeline.py but specifically for Step E
        if data_conf.empty or len(data_conf) < 5:
            return None

        cdf = data_conf.tail(10).copy()
        latest_fvg = None
        latest_ob = None
        
        for i in range(2, len(cdf)):
            c1, c3 = cdf.iloc[i-2], cdf.iloc[i]
            if direction == "long":
                if c3['Low'] > c1['High']:
                    latest_fvg = {'type': 'bullish', 'top': float(c3['Low']), 'bottom': float(c1['High']), 'mean': (c3['Low'] + c1['High']) / 2}
                    # Find OB: last down candle before displacement
                    for j in range(i-1, 0, -1):
                        cand = cdf.iloc[j]
                        if cand['Close'] < cand['Open']:
                            latest_ob = {'type': 'bullish', 'high': float(cand['High']), 'low': float(cand['Low']), 'mean': float((cand['High'] + cand['Low']) / 2)}
                            break
            else:
                if c3['High'] < c1['Low']:
                    latest_fvg = {'type': 'bearish', 'top': float(c1['Low']), 'bottom': float(c3['High']), 'mean': (c1['Low'] + c3['High']) / 2}
                    # Find OB: last up candle before displacement
                    for j in range(i-1, 0, -1):
                        cand = cdf.iloc[j]
                        if cand['Close'] > cand['Open']:
                            latest_ob = {'type': 'bearish', 'high': float(cand['High']), 'low': float(cand['Low']), 'mean': float((cand['High'] + cand['Low']) / 2)}
                            break
        
        return {"fvg": latest_fvg, "ob": latest_ob}

    def process_symbol(self, symbol, market_data):
        """
        Orchestrates the 5-step sequence for a symbol.
        market_data: { '1m', '5m', '15m', '1d' } DataFrames
        """
        # Step A: Update levels daily/periodically
        levels = self.update_institutional_levels(symbol, market_data['5m'], market_data['1d'])
        if not levels: return None

        current_price = market_data['1m']['Close'].iloc[-1]
        
        # check if we already have an active setup in progress
        setup = self.active_setups.get(symbol)
        
        if not setup:
            # Step B: Sweep Detection
            sweep = self.detect_sweep(symbol, current_price, levels, market_data['15m'])
            if sweep:
                direction = "long" if sweep['type'] == "bullish_sweep" else "short"
                self.active_setups[symbol] = {
                    "step": "B",
                    "direction": direction,
                    "sweep_info": sweep,
                    "timestamp": datetime.now(timezone.utc)
                }
                print(f"[{symbol}] STEP B: {sweep['type']} detected at {sweep['price']}")
        
        setup = self.active_setups.get(symbol)
        if setup:
            # Check for Step C (Displacement) if at Step B
            if setup['step'] == "B":
                if self.detect_displacement(symbol, setup['sweep_info'], market_data['15m']):
                    setup['step'] = "C"
                    print(f"[{symbol}] STEP C: Displacement confirmed for {setup['direction']}")
                # Timeout setup if it takes too long? (e.g. 4 hours)
                elif (datetime.now(timezone.utc) - setup['timestamp']).total_seconds() > 4 * 3600:
                    del self.active_setups[symbol]
                    return None

            # Check for Step D (MSS) if at Step C
            if setup['step'] == "C":
                if self.detect_mss(symbol, setup['direction'], market_data['5m']): # Use 5m for MSS
                    setup['step'] = "D"
                    print(f"[{symbol}] STEP D: MSS confirmed for {setup['direction']}")
                elif (datetime.now(timezone.utc) - setup['timestamp']).total_seconds() > 6 * 3600:
                    del self.active_setups[symbol]
                    return None

            # Check for Step E (Entry) if at Step D
            if setup['step'] == "D":
                zones = self.get_fvg_ob_zone(symbol, setup['direction'], market_data['1m'])
                if zones and (zones['fvg'] or zones['ob']):
                    # Check if price is in 50% zone
                    target_zone = zones['fvg'] if zones['fvg'] else zones['ob']
                    if setup['direction'] == "long":
                        if current_price <= target_zone['mean']:
                            print(f"[{symbol}] STEP E: Entry Triggered at {current_price}")
                            del self.active_setups[symbol] # Reset for next setup
                            return {"symbol": symbol, "direction": "long", "price": current_price, "sl": target_zone['bottom'] if zones['fvg'] else target_zone['low']}
                    else:
                        if current_price >= target_zone['mean']:
                            print(f"[{symbol}] STEP E: Entry Triggered at {current_price}")
                            del self.active_setups[symbol]
                            return {"symbol": symbol, "direction": "short", "price": current_price, "sl": target_zone['top'] if zones['fvg'] else target_zone['high']}

        return None
