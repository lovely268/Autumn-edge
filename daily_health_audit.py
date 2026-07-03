import json
import os
from datetime import datetime, timezone
import config

STATE_FILE = config.STATE_FILE
PORTFOLIO_FILE = config.PORTFOLIO_FILE
LOG_DIR = config.LOG_DIR
BASE_DIR = config.BASE_DIR

def run_health_audit():
    print(f"--- Aurum Edge Master Health Audit ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")
    
    # 1. Check Processes
    # (Assuming we run this on the server)
    import subprocess
    ps = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
    pipeline_running = 'pipeline_service.py' in ps.stdout
    execution_running = 'execution_agent.py' in ps.stdout
    watchdog_running = 'watchdog.py' in ps.stdout
    
    print(f"Watchdog: {'[OK]' if watchdog_running else '[DOWN]'}")
    print(f"Pipeline Service: {'[OK]' if pipeline_running else '[DOWN]'}")
    print(f"Execution Agent: {'[OK]' if execution_running else '[DOWN]'}")
    
    # 2. Check State
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        print(f"Market State: Active ({len(state)} symbols scanned)")
        # Show top 3 scores
        scores = sorted([(s, market.get('ml_score', 0)) for s, market in state.items() if s != '_global' and isinstance(market, dict)], key=lambda x: x[1], reverse=True)
        print(f"Top 3 Institutional Scores: {scores[:3]}")
    else:
        print("Market State: [MISSING]")
        
    # 3. Check Portfolio
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            portfolio = json.load(f)
        print(f"Account Balance: ${portfolio.get('balance', 0):.2f}")
        print(f"Daily PnL: ${portfolio.get('daily_pnl', 0):.2f} ({portfolio.get('daily_pnl', 0)/portfolio.get('balance', 100)*100:.2f}%)")
        active_pos = [s for s, p in portfolio.get('positions', {}).items() if p]
        print(f"Active Positions: {active_pos if active_pos else 'None'}")
    else:
        print("Portfolio: [MISSING]")
        
    # 4. Check Logs for Errors
    print("\nRecent Log Alerts (Errors/Restarts):")
    watchdog_log = f"{LOG_DIR}/watchdog.log"
    if os.path.exists(watchdog_log):
        with open(watchdog_log, "r") as f:
            lines = f.readlines()
            for line in lines[-10:]:
                if "RESTARTING" in line or "Error" in line:
                    print(f"  [Watchdog] {line.strip()}")
    
    # 5. Export Health Status
    health_status = {
        "status": "PASS" if all([watchdog_running, pipeline_running, execution_running]) else "FAIL",
        "timestamp": datetime.now().isoformat(),
        "reason": "" if all([watchdog_running, pipeline_running, execution_running]) else "One or more processes DOWN"
    }
    with open(f"{BASE_DIR}/health_status.json", "w") as f:
        json.dump(health_status, f, indent=4)
    
    print("\n--- Audit Complete ---")

if __name__ == "__main__":
    run_health_audit()
