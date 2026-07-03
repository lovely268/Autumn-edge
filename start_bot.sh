#!/bin/bash

# Configuration - Relative paths for portability
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
LOG_DIR="$SCRIPT_DIR/logs"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

echo "Stopping existing bot processes and watchdog..."
pkill -f "watchdog.py"
pkill -f "pipeline_service.py"
pkill -f "execution_agent.py"
sleep 2

echo "Starting Watchdog Service (which will manage other processes)..."
cd "$SCRIPT_DIR"
nohup python3 -u watchdog.py > "$LOG_DIR/watchdog_service.log" 2>&1 &

echo "Aurum Edge bot processes managed by Watchdog started in background."
echo "Running from: $SCRIPT_DIR"
echo "Logs: $LOG_DIR"

# Basic validation
sleep 5
ps aux | grep -E "watchdog.py|pipeline_service.py|execution_agent.py" | grep -v grep
