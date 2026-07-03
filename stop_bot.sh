#!/bin/bash

echo "Stopping Aurum Edge bot processes and watchdog..."

pkill -f "watchdog.py"
pkill -f "pipeline_service.py"
pkill -f "execution_agent.py"

sleep 1
echo "Current status:"
ps aux | grep -E "watchdog.py|pipeline_service.py|execution_agent.py" | grep -v grep || echo "Bot processes stopped."
