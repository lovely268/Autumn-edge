#!/usr/bin/env python3
"""
Aurum Edge Watchdog — Health Monitoring & Auto-Restart
Checks the webhook server health endpoint every 5 minutes.
Restarts the server if it becomes unresponsive.
"""
import os
import sys
import time
import json
import subprocess
import requests

HEALTH_URL = "http://localhost:3000/health"
CHECK_INTERVAL = 300  # 5 minutes
SERVER_CMD = "python3 main.py"

def check_health():
    """Hit the /health endpoint and return parsed JSON or None."""
    try:
        resp = requests.get(HEALTH_URL, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[WATCHDOG] Health check failed: {e}", flush=True)
    return None

def check_process():
    """Check if main.py is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python3 main.py"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

def restart_server():
    """Restart the webhook server process."""
    print("[WATCHDOG] Restarting server...", flush=True)
    try:
        # Kill existing process
        subprocess.run(["pkill", "-f", "python3 main.py"], timeout=5)
        time.sleep(2)
        # Start new process
        subprocess.Popen(
            ["python3", "main.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        print("[WATCHDOG] Server restarted successfully", flush=True)
    except Exception as e:
        print(f"[WATCHDOG] Restart failed: {e}", flush=True)

def main():
    print("[WATCHDOG] Starting Aurum Edge Watchdog...", flush=True)
    
    # Initial start if not running
    if not check_process():
        restart_server()
        time.sleep(5)

    while True:
        alive = check_process()
        health = check_health()

        if not alive:
            print("[WATCHDOG] Server process not found. Restarting...", flush=True)
            restart_server()
        elif health is None:
            print("[WATCHDOG] Health endpoint unresponsive. Restarting...", flush=True)
            restart_server()
        else:
            status = health.get("status", "unknown")
            pnl = health.get("daily_pnl", 0)
            total = health.get("total_pnl", 0)
            print(f"[WATCHDOG] OK — Status: {status} | Daily PnL: ${pnl:.2f} | Total: ${total:.2f}", flush=True)

            # Alert if pass conditions met
            pass_conds = health.get("pass_conditions", {})
            if pass_conds.get("all_met", False):
                alert_sent = health.get("pass_alert_sent", False)
                if alert_sent:
                    print("[WATCHDOG] 🚀 EVALUATION PASS CONDITIONS MET!", flush=True)

            # Alert if account floor breached
            if health.get("account_floor_warning", False):
                print(f"[WATCHDOG] ⚠️ Account floor WARNING — balance near $24,000 threshold", flush=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()