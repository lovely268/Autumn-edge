import time
import json
import os
import pandas as pd
from datetime import datetime, timezone, timedelta
import config
from oanda_execution import OandaExecution
from futures_execution import FuturesExecution
from telegram_notify import send_telegram_message, format_trade_alert, format_exit_alert, format_status_alert, format_setup_alert

# Absolute paths
STATE_FILE = config.STATE_FILE
PORTFOLIO_FILE = config.PORTFOLIO_FILE

def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            portfolio = json.load(f)
            # Migration/Defaults for new fields
            if 'consecutive_losses' not in portfolio: portfolio['consecutive_losses'] = 0
            if 'pause_until' not in portfolio: portfolio['pause_until'] = None
            if 'sniper_setups' not in portfolio: portfolio['sniper_setups'] = {}
            return portfolio
    return {
        'balance': config.ACCOUNT_SIZE,
        'positions': {},
        'pending_setups': {},
        'sniper_setups': {},
        'daily_pnl': 0,
        'last_pnl_reset': str(datetime.now(timezone.utc).date()),
        'consecutive_losses': 0,
        'pause_until': None
    }

def save_portfolio(portfolio):
    temp_portfolio = PORTFOLIO_FILE + ".tmp"
    with open(temp_portfolio, "w") as f:
        json.dump(portfolio, f, indent=4)
    os.replace(temp_portfolio, PORTFOLIO_FILE)

def check_price_action(setup_type, conf_candles):
    """
    Implements Phase 2 Precision:
    Layer 6: Wick Rejection (>50% of candle)
    Layer 7: Structural Break (Body close past recent swing)
    """
    if len(conf_candles) < 10: return False
    df = pd.DataFrame(conf_candles)
    
    # Layer 6: Wick-to-Body Ratio Filtering (Institutional Rejection)
    # Check last 5 candles for a significant wick rejection at the extreme
    rejection_found = False
    last_5 = df.tail(5)
    for _, row in last_5.iterrows():
        total_size = row['high'] - row['low']
        if total_size <= 0: continue
        
        if setup_type == "long":
            # Bullish rejection: large LOWER wick
            lower_wick = min(row['open'], row['close']) - row['low']
            if (lower_wick / total_size) >= 0.5:
                rejection_found = True
                break
        else:
            # Bearish rejection: large UPPER wick
            upper_wick = row['high'] - max(row['open'], row['close'])
            if (upper_wick / total_size) >= 0.5:
                rejection_found = True
                break
                
    if not rejection_found:
        return False
        
    # Layer 7: Structural Break (BOS) with Body Close Confirmation
    # Must close past the recent swing high/low (last 10 candles)
    if setup_type == "long":
        recent_swing_high = df['high'].iloc[-10:-1].max()
        if df['close'].iloc[-1] > recent_swing_high:
            return True
    elif setup_type == "short":
        recent_swing_low = df['low'].iloc[-10:-1].min()
        if df['close'].iloc[-1] < recent_swing_low:
            return True
            
    return False

def check_sniper_entry(setup_type, current_price, market):
    """
    Layer 8: Sniper Entry (Return to Value)
    Checks if price has touched the 50% Mean Threshold of the Order Block.
    """
    ob = market.get('latest_ob')
    if not ob: return False
    
    sniper_level = ob['mean']
    
    if setup_type == "long":
        # Retrace DOWN to OB Mean
        return current_price <= sniper_level
    else:
        # Retrace UP to OB Mean
        return current_price >= sniper_level

def check_order_flow(setup_type, market):
    """
    Layer 9: Order Flow Alpha (Institutional Pressure)
    Checks Volume Delta and Position Ratios to confirm institutional direction.
    """
    net_vol = market.get('net_volume_delta', 0)
    long_pos = market.get('long_pos', 50)
    short_pos = market.get('short_pos', 50)
    
    if setup_type == "long":
        # Long confirmed if buying pressure or shorts are trapped (>60% short)
        return net_vol > 0 or short_pos > 60
    else:
        # Short confirmed if selling pressure or longs are trapped (>60% long)
        return net_vol < 0 or long_pos > 60

def is_within_session(symbol):
    now_utc = datetime.now(timezone.utc)
    current_time = now_utc.hour + now_utc.minute / 60.0
    
    # Global End Gate (1 PM ET = 17 UTC)
    if current_time >= config.GLOBAL_ENTRY_END_UTC: return False
    
    # Friday Stop (12 PM ET = 16 UTC)
    if now_utc.weekday() == 4 and current_time >= config.FRIDAY_STOP_UTC: return False
    
    # Sunday Start (5 PM ET = 21 UTC)
    if now_utc.weekday() == 6 and current_time < config.SUNDAY_START_UTC: return False

    # Pair specific gates
    gates = config.SESSION_GATES.get(symbol)
    if not gates: return True # Default to allow if no specific gate
    
    for start, end in gates:
        if start <= current_time < end: return True
        if start > end: # Overlap midnight (e.g. 22 to 4)
            if current_time >= start or current_time < end: return True
            
    return False

def get_spread_limit(symbol):
    if symbol in config.TIER_1: return config.SPREAD_LIMITS["TIER_1"]
    if symbol in config.TIER_2: return config.SPREAD_LIMITS["TIER_2"]
    if symbol in config.TIER_3: return config.SPREAD_LIMITS["TIER_3"]
    return config.SPREAD_LIMITS["TIER_4"]

def get_pair_tier(symbol):
    if symbol in config.TIER_1: return 1
    if symbol in config.TIER_2: return 2
    if symbol in config.TIER_3: return 3
    return 4

def execute_entry(symbol, market, portfolio, oanda, futures_exec, timestamp_str):
    price = market.get('latest_price')
    if price is None: return
    atr = market.get('latest_atr', 0.0001)
    entry_type = portfolio['pending_setups'][symbol]

    # Phase 4 Upgrade: Use direction-specific score for RR scaling
    ml_score = market.get('long_score', 0) if entry_type == "long" else market.get('short_score', 0)

    is_futures = "=F" in symbol

    # 1. Spread Filter & Price Calibration
    if not is_futures and oanda:
        oanda_symbol = symbol.replace("=X", "").replace("USDJPY", "USD_JPY").replace("EURUSD", "EUR_USD").replace("GBPUSD", "GBP_USD")
        if "_" not in oanda_symbol and len(oanda_symbol) == 6:
            oanda_symbol = oanda_symbol[:3] + "_" + oanda_symbol[3:]

        spread = oanda.get_spread(oanda_symbol)
        if spread is not None:
            limit = get_spread_limit(symbol)
            is_gold = "XAU" in oanda_symbol
            actual_spread = spread if is_gold else spread * (100 if "JPY" in symbol else 10000)
            if actual_spread > limit:
                print(f"[{timestamp_str}] [{symbol}] SKIPPING: Spread too wide ({actual_spread:.2f} > {limit})", flush=True)
                return

        oanda_price = oanda.get_current_price(oanda_symbol)
        if oanda_price: price = oanda_price

    # Phase 4 Upgrade: Dynamic Risk-Reward (RR) Scaling
    rr_target = 3.0 # Default
    if ml_score >= 9: rr_target = 4.0
    elif ml_score >= 7: rr_target = 3.0
    else: rr_target = 1.5

    # 2. Risk & Sizing (Phase 5: Kelly Criterion Evolution)
    prob_win = ml_score / 10.0 if ml_score else 0.5
    q = 1.0 - prob_win
    b = rr_target
    kelly_f = (b * prob_win - q) / b if b != 0 else 0
    
    if kelly_f < 0: kelly_f = 0

    # 5.5 Institutional Guardrails: Half-Kelly capped at 4%
    risk_pct = max(0.005, min(0.04, kelly_f * 0.5))

    # Upgrade 7: Circuit Breaker - 2 losses -> Halve Kelly Risk
    if portfolio.get('consecutive_losses', 0) == 2:
        risk_pct = risk_pct * 0.5
        print(f"[{symbol}] Circuit Breaker: 2 losses detected. Halving Kelly risk to {risk_pct*100:.2f}%")

    risk_dist = atr * config.DISP_MULT
    sl_price = price - risk_dist if entry_type == "long" else price + risk_dist

    tp1_rr = max(1.2, rr_target * 0.5)
    tp2_rr = rr_target

    tp1_price = price + (risk_dist * tp1_rr) if entry_type == "long" else price - (risk_dist * tp1_rr)
    tp2_price = price + (risk_dist * tp2_rr) if entry_type == "long" else price - (risk_dist * tp2_rr)
    tp3_price = price + (risk_dist * 5.0) if entry_type == "long" else price - (risk_dist * 5.0)

    risk_amount = portfolio['balance'] * risk_pct

    size_total = 0
    if is_futures and futures_exec:
        size_total = futures_exec.calculate_position_size(risk_amount, risk_dist, symbol)
    elif oanda:
        oanda_symbol = symbol.replace("=X", "").replace("USDJPY", "USD_JPY").replace("EURUSD", "EUR_USD").replace("GBPUSD", "GBP_USD")
        if "_" not in oanda_symbol and len(oanda_symbol) == 6:
            oanda_symbol = oanda_symbol[:3] + "_" + oanda_symbol[3:]
        size_total = oanda.calculate_position_size(risk_amount, risk_dist, oanda_symbol)
    else:
        size_total = 1 # Simulation default

    if size_total <= 0: return

    # For Futures, we don't always split into 3 parts if contracts < 3
    if is_futures and size_total < 3:
        parts = [{'units': size_total, 'tp': tp2_price, 'label': 'TP2 (3.0:1)', 'is_trailing': True}]
    else:
        part_size = size_total // 3
        if part_size == 0: part_size = size_total
        parts = [
            {'units': part_size, 'tp': tp1_price, 'label': 'TP1 (1.5:1)'},
            {'units': part_size, 'tp': tp2_price, 'label': 'TP2 (3.0:1)'},
            {'units': size_total - (2 * part_size), 'tp': tp3_price, 'label': 'TP3 (Trail)', 'is_trailing': True}
        ]

    trade_parts = []
    for part in parts:
        if part['units'] <= 0: continue
        exec_id = None
        if is_futures and futures_exec:
            res = futures_exec.execute_market_order(entry_type, part['units'], sl_price, part['tp'], symbol)
            if res: exec_id = res.get('lastTransactionID')
        elif oanda:
            res = oanda.execute_market_order(entry_type, part['units'], sl_price, part['tp'], instrument=oanda_symbol)
            if res: exec_id = res.get('lastTransactionID')
        else:
            exec_id = f"sim_{symbol}_{entry_type}"

        trade_parts.append({
            'id': exec_id,
            'units': part['units'],
            'tp': part['tp'],
            'status': 'open',
            'label': part['label'],
            'is_trailing': part.get('is_trailing', False)
        })

    portfolio['positions'][symbol] = {
        'type': entry_type, 'entry_price': price, 'stop_loss': sl_price,
        'initial_sl': sl_price, 'risk_amount': risk_amount,
        'ml_score': ml_score, 'be_active': False,
        'parts': trade_parts,
        'units_total': size_total
    }

    log_trade_journal(symbol, entry_type, size_total, price, sl_price, tp2_price, ml_score, "Executed")
    print(f"[{timestamp_str}] [{symbol}] OPENED {len(parts)}-Part {entry_type}. Size: {size_total}. Risk: ${risk_amount:.2f}", flush=True)

    msg = format_trade_alert(symbol, entry_type, price, sl_price, tp2_price, ml_score)
    send_telegram_message(msg)

    portfolio['pending_setups'][symbol] = None
    save_portfolio(portfolio)

def log_trade_journal(symbol, direction, units, entry, sl, tp, score, status, result="", pnl=0):
    journal_path = os.path.join(config.SHARED_DIR, "trade_journal.csv")
    import csv
    file_exists = os.path.isfile(journal_path)
    
    # Convert UTC to ET (rough proxy -4h)
    et_time = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime('%Y-%m-%d %H:%M:%S')
    
    with open(journal_path, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "Pair", "Direction", "Lot Size", "Entry Price", "Stop Loss", "Take Profit 1", "Take Profit 2", "Score", "Session", "Setup Type", "Status", "Result", "P&L"])
        
        # strategy: TP1 at 1.5R, TP2 at 3.0R
        risk_dist = abs(entry - sl)
        tp1 = entry + (risk_dist * 1.5) if direction == "long" else entry - (risk_dist * 1.5)
        tp2_target = tp # This is the 3.0R target passed in
        
        writer.writerow([et_time, symbol.replace("=X",""), direction.upper(), units/100000, entry, sl, tp1, tp2_target, f"{score}/10", "Active Session", "Session Sweep", status, result, f"${pnl:.2f}"])

def run_execution_agent():
    print(f"Aurum Edge Execution Agent (Hardened 12-Priority) starting...", flush=True)
    portfolio = load_portfolio()
    oanda = OandaExecution() if config.LIVE_MODE else None
    futures_exec = FuturesExecution()
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Daily PnL Reset (00:00 UTC for simplicity, or 00:00 ET per Rule 4)
            # ET 00:00 = UTC 04:00
            pnl_reset_time = (now - timedelta(hours=4)).date()
            if str(pnl_reset_time) != portfolio.get('last_pnl_reset'):
                print(f"New trading day ({pnl_reset_time}). Resetting daily PnL.")
                # Telegram Alert: Daily Summary
                summary = f"<b>📅 Daily P&L Summary: {portfolio.get('last_pnl_reset')}</b>\nFinal P&L: ${portfolio.get('daily_pnl', 0):.2f}\nBalance: ${portfolio.get('balance', 0):.2f}"
                send_telegram_message(format_status_alert(summary))
                
                portfolio['daily_pnl'] = 0
                portfolio['last_pnl_reset'] = str(pnl_reset_time)
                save_portfolio(portfolio)

            # Rule 4: Daily Loss Limit (3%)
            limit = portfolio['balance'] * config.DAILY_LOSS_LIMIT_PCT
            if portfolio['daily_pnl'] <= -limit:
                # Cancel pending, keep open
                portfolio['pending_setups'] = {}
                save_portfolio(portfolio)
                print(f"Daily loss limit reached (${portfolio['daily_pnl']:.2f}). Trading halted.", flush=True)
                time.sleep(300)
                continue

            # Upgrade 7: Circuit Breaker - 4 losses Day Halt
            if portfolio.get('consecutive_losses', 0) >= 4:
                print(f"Circuit Breaker: 4 consecutive losses. Day halt active.", flush=True)
                send_telegram_message(format_status_alert("🚨 <b>CRITICAL:</b> 4 consecutive losses detected. Trading halted for the day."))
                time.sleep(300); continue

            # Upgrade 7: Circuit Breaker - 3 losses 4hr Pause
            if portfolio.get('pause_until'):
                pause_time = datetime.fromisoformat(portfolio['pause_until'])
                if now < pause_time:
                    print(f"Circuit Breaker: 3 consecutive losses. Paused until {pause_time}.", flush=True)
                    # We only send this alert once when the pause starts (handled by the check below)
                    time.sleep(300); continue
                else:
                    portfolio['pause_until'] = None
                    save_portfolio(portfolio)
                    send_telegram_message(format_status_alert("🛡️ Circuit Breaker: 4-hour pause expired. Resuming operations."))

            if not os.path.exists(STATE_FILE):
                time.sleep(5); continue
            
            # Hardened JSON Load with Retries
            master_state = None
            for _ in range(3):
                try:
                    with open(STATE_FILE, "r") as f:
                        master_state = json.load(f)
                    if master_state: break
                except (json.JSONDecodeError, ValueError):
                    time.sleep(1)
            
            if not master_state:
                continue

            # Rule: Hard Close at 4:30 PM ET (Rule 5)
            current_hour_utc = now.hour + now.minute / 60.0
            if current_hour_utc >= config.HARD_CLOSE_UTC:
                for symbol, pos in list(portfolio['positions'].items()):
                    if pos:
                        print(f"[{symbol}] Hard Close reached ({config.HARD_CLOSE_UTC} UTC). Closing all positions.")
                        for part in pos['parts']:
                            if part['status'] == 'open' and part['id']:
                                if "=F" in symbol:
                                    futures_exec.close_trade(part['id'])
                                else:
                                    oanda.close_trade(part['id'])
                        portfolio['positions'][symbol] = None
                save_portfolio(portfolio)
                # After hard close, wait until next session
                time.sleep(300)
                continue

            # Active Currencies for Correlation Block (Rule 2)
            active_currencies = {} # 'USD': 'long'
            for s, p in portfolio['positions'].items():
                if p:
                    base, quote = s[:3], s[3:6]
                    active_currencies[base] = 'long' if p['type'] == 'long' else 'short'
                    active_currencies[quote] = 'short' if p['type'] == 'long' else 'long'

            # Rule: Weekly Equity Halt (10%)
            week_start = portfolio.get('week_start_equity', portfolio['balance'])
            if portfolio['balance'] <= week_start * (1 - config.TOTAL_EQUITY_HALT_PCT):
                print(f"CRITICAL: Weekly Equity Halt Reached. Trading Paused.")
                time.sleep(3600)
                continue

            # 1.5 Futures Step-Sequence Execution
            for symbol, market in master_state.items():
                if not isinstance(market, dict) or "=F" not in symbol: continue
                if portfolio['positions'].get(symbol): continue
                
                futures_setup = market.get('futures_setup')
                if futures_setup:
                    print(f"[{symbol}] Futures Setup Triggered: {futures_setup['direction']} at {futures_setup['price']}")
                    # Update pending_setups to trigger entry
                    portfolio['pending_setups'][symbol] = futures_setup['direction']
                    execute_entry(symbol, market, portfolio, None, futures_exec, market['timestamp'])
                    save_portfolio(portfolio)

            # 1. Manage Exits (Simulation & Management)
            for symbol, pos in list(portfolio['positions'].items()):
                if not pos: continue
                market = master_state.get(symbol)
                if not market: continue
                price = market.get('latest_price')
                if price is None or pd.isna(price): continue
                
                atr = market.get('latest_atr', 0.0001)
                entry = pos['entry_price']
                initial_sl = pos.get('initial_sl', pos['stop_loss'])
                risk_dist = abs(entry - initial_sl)
                if risk_dist == 0: risk_dist = 0.0001
                
                # Calculate current RR
                current_pips = (price - entry) if pos['type'] == 'long' else (entry - price)
                current_rr = current_pips / risk_dist
                
                # Rule: Move to Break-even at 1:1 RR
                if current_rr >= 1.0 and not pos.get('be_active'):
                    spread_proxy = 0.0001 if "JPY" not in symbol else 0.01
                    pos['stop_loss'] = entry + spread_proxy if pos['type'] == 'long' else entry - spread_proxy
                    pos['be_active'] = True
                    # Update SL on Oanda for all open parts
                    if oanda:
                        for part in pos['parts']:
                            if part['status'] == 'open' and part['id']:
                                oanda.modify_stop_loss(part['id'], pos['stop_loss'], symbol.replace("=X",""))
                    print(f"[{symbol}] Break-even activated at 1:1 RR.")

                # Check each part
                any_part_open = False
                for part in pos['parts']:
                    if part['status'] != 'open': continue
                    
                    # 1. Check TP hit
                    tp_hit = False
                    if pos['type'] == 'long' and price >= part['tp']: tp_hit = True
                    elif pos['type'] == 'short' and price <= part['tp']: tp_hit = True
                    
                    if tp_hit:
                        pnl_part = (abs(part['tp'] - entry) / risk_dist) * (pos['risk_amount'] * (part['units'] / pos['units_total']))
                        portfolio['balance'] += pnl_part
                        portfolio['daily_pnl'] += pnl_part
                        part['status'] = 'closed'
                        if oanda and part['id']:
                            oanda.close_trade(part['id'])
                        log_trade_journal(symbol, pos['type'], part['units'], entry, initial_sl, part['tp'], pos['ml_score'], f"TP Hit: {part['label']}", "Target Hit", pnl_part)
                        print(f"[{symbol}] Part {part['label']} hit TP. PnL: ${pnl_part:.2f}")
                        
                        # Telegram Alert: TP
                        exit_msg = format_exit_alert(symbol, f"TP Hit: {part['label']}", pnl_part, portfolio['daily_pnl'])
                        send_telegram_message(exit_msg)
                        
                        continue
                    
                    # 2. Check SL hit
                    sl_hit = False
                    if pos['type'] == 'long' and price <= pos['stop_loss']: sl_hit = True
                    elif pos['type'] == 'short' and price >= pos['stop_loss']: sl_hit = True
                    
                    if sl_hit:
                        # PnL could be negative or positive (if BE/Trail)
                        pnl_part = ((pos['stop_loss'] - entry) / risk_dist if pos['type'] == 'long' else (entry - pos['stop_loss']) / risk_dist) * (pos['risk_amount'] * (part['units'] / pos['units_total']))
                        portfolio['balance'] += pnl_part
                        portfolio['daily_pnl'] += pnl_part
                        part['status'] = 'closed'
                        if oanda and part['id']:
                            oanda.close_trade(part['id'])
                        
                        # Circuit Breaker tracking for losses
                        if pnl_part < 0:
                            portfolio['consecutive_losses'] += 1
                            if portfolio['consecutive_losses'] == 3:
                                portfolio['pause_until'] = (now + timedelta(hours=config.CIRCUIT_BREAKER_3_LOSS_PAUSE_HOURS)).isoformat()
                                send_telegram_message(format_status_alert(f"🛡️ <b>Circuit Breaker:</b> 3 consecutive losses. Trading paused for {config.CIRCUIT_BREAKER_3_LOSS_PAUSE_HOURS} hours."))
                        else:
                            portfolio['consecutive_losses'] = 0

                        log_trade_journal(symbol, pos['type'], part['units'], entry, initial_sl, part['tp'], pos['ml_score'], "SL Hit", "Stop Hit", pnl_part)
                        print(f"[{symbol}] Part {part['label']} hit SL. PnL: ${pnl_part:.2f}")
                        
                        # Telegram Alert: SL
                        exit_msg = format_exit_alert(symbol, "SL Hit", pnl_part, portfolio['daily_pnl'])
                        send_telegram_message(exit_msg)
                        
                        continue
                    
                    # 3. Handle Trailing for Part 3 (1x ATR Trail)
                    if part.get('is_trailing'):
                        # Trail if current RR > 1.5 (once TP1 is hit)
                        if current_rr >= 1.5:
                            trail_dist = atr # 1x ATR trail
                            new_sl = price - trail_dist if pos['type'] == 'long' else price + trail_dist
                            
                            # Only move SL if it improves protection
                            moved = False
                            if pos['type'] == 'long' and new_sl > pos['stop_loss']:
                                pos['stop_loss'] = new_sl
                                moved = True
                            elif pos['type'] == 'short' and new_sl < pos['stop_loss']:
                                pos['stop_loss'] = new_sl
                                moved = True
                            
                            if moved and oanda and part['id']:
                                oanda.modify_stop_loss(part['id'], pos['stop_loss'], symbol.replace("=X",""))

                    any_part_open = True
                
                if not any_part_open:
                    portfolio['positions'][symbol] = None
                    save_portfolio(portfolio)

            # 2. Detect Sweeps & Update Target Queue (pending_setups)
            current_sweeps = {}
            for symbol, market in master_state.items():
                if not isinstance(market, dict) or 'session_boundaries' not in market: continue
                if portfolio['positions'].get(symbol): continue
                price = market.get('latest_price')
                if price is None or pd.isna(price): continue
                
                bounds = market['session_boundaries']
                
                setup = None
                # Check Asian, London, and Previous Day (PD) sweeps
                for session in ['asian', 'london', 'pd']:
                    high = bounds[session].get('high')
                    low = bounds[session].get('low')
                    if high and price > high: 
                        setup = "short"
                        break
                    elif low and price < low: 
                        setup = "long"
                        break

                if setup:
                    tier = get_pair_tier(symbol)
                    
                    # Phase 4 Fusion Core: Use Scorer's Gating logic
                    is_gated = market.get('is_long_gated', True) if setup == "long" else market.get('is_short_gated', True)
                    score = market.get('long_score', 0) if setup == "long" else market.get('short_score', 0)
                    
                    if score is None: score = 0
                    
                    if not is_gated and score >= 8.5:
                        current_sweeps[symbol] = {
                            'setup': setup, 'score': score,
                            'base': symbol[:3], 'tier': tier
                        }
                    else:
                        if now.second % 30 == 0:
                            failures = market.get('gate_failures', [])
                            print(f"[{symbol}] GATED: Setup {setup} failed confluence ({score}/10). Failures: {failures}")
            # Apply Queue Guardrails: 1 per base currency, top 3 by score
            by_base = {}
            for symbol, data in current_sweeps.items():
                base = data['base']
                if base not in by_base or data['score'] > by_base[base]['score']:
                    by_base[base] = {'symbol': symbol, **data}
            top_candidates = sorted(by_base.values(), key=lambda x: x['score'], reverse=True)[:3]
            portfolio['pending_setups'] = {c['symbol']: c['setup'] for c in top_candidates}

            # 3. Process Sniper Entries (Layer 8)
            active_pos_count = sum(1 for p in portfolio['positions'].values() if p)
            if active_pos_count < config.MAX_CONCURRENT_POSITIONS:
                for symbol, sniper in list(portfolio.get('sniper_setups', {}).items()):
                    if not sniper: 
                        portfolio.get('sniper_setups', {}).pop(symbol, None)
                        continue
                        
                    market = master_state.get(symbol)
                    if not market: continue
                    price = market.get('latest_price')
                    if price is None: continue
                    
                    # Staleness check (2 hours)
                    setup_time = datetime.fromisoformat(sniper['timestamp'])
                    if now - setup_time > timedelta(hours=2):
                        print(f"[{symbol}] Sniper Setup Stale (2h+). Removing.")
                        portfolio['sniper_setups'].pop(symbol, None)
                        continue

                    if check_sniper_entry(sniper['type'], price, market):
                        print(f"[{symbol}] Sniper Entry Triggered at {price} (Target OB Mean Reached)")
                        execute_entry(symbol, market, portfolio, oanda, futures_exec, market['timestamp'])
                        portfolio['sniper_setups'].pop(symbol, None)
                        save_portfolio(portfolio)
                        active_pos_count += 1
                        if active_pos_count >= config.MAX_CONCURRENT_POSITIONS: break

            # 4. Filter and Rank Pending for Sniper Queue
            if active_pos_count < config.MAX_CONCURRENT_POSITIONS:
                for symbol, setup in list(portfolio['pending_setups'].items()):
                    if not setup: continue
                    market = master_state.get(symbol)
                    if not market: continue
                    
                    if portfolio.get('sniper_setups', {}).get(symbol): continue
                    if portfolio['positions'].get(symbol): continue
                    
                    # Rule 6: Session Gates
                    if not is_within_session(symbol): continue
                    
                    # Rule 12: News
                    if market.get('news_active'): continue
                    
                    # Layer 9: Order Flow Alpha
                    if not check_order_flow(setup, market): continue
                    
                    # Rule 2: Correlation Block
                    base, quote = symbol[:3], symbol[3:6]
                    if base in active_currencies or quote in active_currencies: continue
                    
                    # Rule 5: Tier & Min Score
                    tier = get_pair_tier(symbol)
                    min_score = config.MIN_SCORES.get(f"TIER_{tier}", 8)
                    if market.get('ml_score', 0) < min_score: continue
                    
                    # Layer 6 & 7 PA Check
                    if check_price_action(setup, market.get('conf_candles', [])):
                        ob = market.get('latest_ob')
                        if ob:
                            portfolio['sniper_setups'][symbol] = {
                                'type': setup,
                                'level': ob['mean'],
                                'timestamp': now.isoformat()
                            }
                            print(f"[{symbol}] BOS Confirmed. Sniper Target Set: {ob['mean']}. Awaiting retracement...")
                            send_telegram_message(format_setup_alert(symbol, setup, ob['mean'], market.get('ml_score', 0)))
                            save_portfolio(portfolio)
                        else:
                            # Fallback if no OB found but BOS confirmed (rare)
                            print(f"[{symbol}] BOS Confirmed but no OB found. Entering at market...")
                            execute_entry(symbol, market, portfolio, oanda, futures_exec, market['timestamp'])
                            active_pos_count += 1

                        # Log status
                        if now.second % 30 == 0:
                            print(f"[{symbol}] Pending PA rejection or BOS confirmation...")

            save_portfolio(portfolio)
            time.sleep(10)
        except Exception as e:
            print(f"Error: {e}"); time.sleep(30)

if __name__ == "__main__":
    run_execution_agent()
