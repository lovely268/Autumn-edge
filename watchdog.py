import time
import subprocess
import os
import logging
from datetime import datetime
from telegram_notify import send_telegram_message, format_status_alert

# Configuration - Relative for portability
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
WATCHDOG_LOG = os.path.join(LOG_DIR, "watchdog.log")
PIPELINE_SCRIPT = "pipeline_service.py"
EXECUTION_SCRIPT = "execution_agent.py"

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Setup logging
logging.basicConfig(
    filename=WATCHDOG_LOG,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def is_process_running(script_name):
    try:
        # Use ps to find processes and grep for the script name, excluding grep and watchdog itself
        cmd = f"ps aux | grep {script_name} | grep -v grep | grep -v watchdog.py"
        output = subprocess.check_output(cmd, shell=True)
        return len(output) > 0
    except subprocess.CalledProcessError:
        return False

def start_process(script_name):
    log_file = os.path.join(LOG_DIR, script_name.replace('.py', '.log'))
    script_path = os.path.join(BASE_DIR, script_name)
    # Use absolute path for python3 and the script
    cmd = f"nohup python3 -u {script_path} > {log_file} 2>&1 &"
    logging.info(f"Restarting {script_name} with command: {cmd}")
    subprocess.Popen(cmd, shell=True, cwd=BASE_DIR)

def monitor():
    logging.info("Watchdog service started.")
    print("Watchdog service started. Monitoring pipeline and execution agent...")
    scripts = [PIPELINE_SCRIPT, EXECUTION_SCRIPT]
    last_health_check = 0
    
    while True:
        try:
            # Run Health Audit every 30 minutes (Rule 11)
            if time.time() - last_health_check > 1800:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running scheduled health audit...")
                audit_path = os.path.join(BASE_DIR, "daily_health_audit.py")
                subprocess.run(["python3", audit_path])
                last_health_check = time.time()

            for script in scripts:
                if not is_process_running(script):
                    logging.warning(f"Process {script} is NOT running!")
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Warning: {script} is NOT running! Restarting...")
                    send_telegram_message(format_status_alert(f"⚠️ <b>Service Failure:</b> {script} is not running. Attempting automatic restart..."))
                    start_process(script)
            
            time.sleep(30) # Check every 30 seconds
        except Exception as e:
            logging.error(f"Error in watchdog loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    monitor()
