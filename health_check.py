import json
import os
import time
from datetime import datetime
import config

STATE_FILE = config.STATE_FILE
PORTFOLIO_FILE = config.PORTFOLIO_FILE
LOG_DIR = config.LOG_DIR

def get_last_line(filepath):
    if not os.path.exists(filepath):
        return "N/A"
    try:
        # Use tail to get last line more efficiently
        return os.popen(f"tail -n 1 {filepath}").read().strip()
    except Exception as e:
        return f"Error: {e}"

def health_check():
    print("--- Aurum Edge Global Scanner Health Check ---")
    
    # 1. Process Check
    pipeline_running = os.system("pgrep -f pipeline_service.py > /dev/null") == 0
    execution_running = os.system("pgrep -f execution_agent.py > /dev/null") == 0
    print(f"Pipeline Service: {'[RUNNING]' if pipeline_running else '[STOPPED]'}")
    print(f"Execution Agent:  {'[RUNNING]' if execution_running else '[STOPPED]'}")

    # 2. Portfolio Check (Top priorities)
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, 'r') as f:
            portfolio = json.load(f)
            balance = portfolio.get('balance', 0)
            print(f"\n--- Portfolio Summary ---")
            print(f"Current Balance:  ${balance:.2f}")
            
            positions = portfolio.get('positions', {})
            active_count = sum(1 for p in positions.values() if p)
            print(f"Active Positions: {active_count}")
            for s, p in positions.items():
                if p:
                    print(f"  - {s}: {p['type'].upper()} @ {p['entry_price']} (Score: {p.get('ml_score')}/10)")
            
            pending = portfolio.get('pending_setups', {})
            pending_list = [s for s, p in pending.items() if p]
            print(f"HUNTING Setups:  {len(pending_list)}")

            # 3. Market State Check (Top 5 Setups)
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    master_state = json.load(f)
                    from scorer import InstitutionalScorer
                    scorer = InstitutionalScorer()
                    
                    print("\n--- GLOBAL SCANNER (Top 5 High-Conviction Setups) ---")
                    # Sort symbols by score
                    sorted_symbols = sorted(master_state.keys(), key=lambda s: master_state[s].get('ml_score', 0), reverse=True)
                    
                    count = 0
                    for symbol in sorted_symbols:
                        if count >= 5: break
                        state = master_state[symbol]
                        score = state.get('ml_score', 0)
                        sentiment = state.get('macro_sentiment', 'N/A')
                        trend = state.get('htf_trend', 'N/A')
                        rating = scorer.get_confidence_rating(score)
                        is_pending = "[HUNTING]" if symbol in pending_list else ""
                        
                        print(f"[{symbol:9}] Score: {score:4}/10 ({rating:25}) {is_pending}")
                        print(f"            Trend: {trend:8} | Sentiment: {sentiment:8}")
                        count += 1
            else:
                print("\nMarket state file missing.")
    else:
        print("\nPortfolio file missing.")

    # 4. Log Heartbeats
    print("\n--- Last Log Entries ---")
    print(f"Pipeline:  {get_last_line(f'{LOG_DIR}/pipeline_service.log')}")
    print(f"Execution: {get_last_line(f'{LOG_DIR}/execution_agent.log')}")

if __name__ == "__main__":
    health_check()
