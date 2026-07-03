# Aurum Edge - External Deployment Guide

This guide provides instructions for deploying the Aurum Edge trading bot on an external Ubuntu VPS (e.g., AWS, DigitalOcean, Hetzner).

## 1. Prerequisites

- A fresh Ubuntu server (22.04 or 24.04 recommended).
- Python 3.10 or higher.
- Oanda Live or Practice Account credentials.

## 2. Server Preparation

Update the server and install basic dependencies:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install git python3-pip python3-venv -y
```

## 3. Deployment Steps

1. **Clone or Copy the Files**
   Upload the `aurum_edge_v1` folder to your server (e.g., to `/home/ubuntu/aurum_edge_v1`).

2. **Set Up a Virtual Environment**
   ```bash
   cd aurum_edge_v1
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**
   Export your Oanda credentials. It's recommended to add these to your `.bashrc` or use a `.env` file with a loader.

   ```bash
   export OANDA_API_KEY="your_api_token"
   export OANDA_ACCOUNT_ID="xxx-xxx-xxxxxxx-xxx"
   export OANDA_ENV="live" # or "practice"
   ```

4. **Launch the Bot**
   The bot is managed by a persistent watchdog that ensures all components (pipeline, execution) remain running.

   ```bash
   chmod +x start_bot.sh stop_bot.sh
   ./start_bot.sh
   ```

## 4. Monitoring

- **Logs:** All logs are stored in the `logs/` directory within the bot folder.
  - `watchdog_service.log`: Watchdog lifecycle and auto-recovery events.
  - `pipeline_service.log`: Market scanning and setup identification.
  - `execution_agent.log`: Order execution and position management.

- **Status:** Check running processes:
  ```bash
  ps aux | grep -E "watchdog.py|pipeline_service.py|execution_agent.py"
  ```

## 5. Maintenance

- **Stopping the Bot:**
  ```bash
  ./stop_bot.sh
  ```

- **Updating Symbols:**
  Modify `config.py` in the root folder and restart the bot.
