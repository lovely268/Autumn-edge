import json
import logging
import urllib.request
import urllib.error
import config

def send_telegram_message(message):
    """
    Sends a message to the configured Telegram chat using urllib (no dependencies).
    """
    if not config.TELEGRAM_ENABLED:
        return False
    
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    req.add_header('Content-Type', 'application/json')
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.getcode() == 200
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        logging.error(f"Telegram notification failed (HTTP {e.code}): {error_body}")
        return False
    except Exception as e:
        logging.error(f"Telegram notification failed: {e}")
        return False

def format_trade_alert(symbol, setup_type, entry, sl, tp, score):
    """
    Formats a professional institutional trade alert.
    """
    emoji = "🚀" if setup_type == "long" else "📉"
    msg = (
        f"<b>{emoji} Aurum Edge Sniper Entry</b>\n\n"
        f"<b>Symbol:</b> {symbol.replace('=X', '')}\n"
        f"<b>Action:</b> {setup_type.upper()}\n"
        f"<b>Price:</b> {entry:.5f}\n"
        f"<b>Stop Loss:</b> {sl:.5f}\n"
        f"<b>Take Profit:</b> {tp:.5f}\n"
        f"<b>ML Conviction:</b> {score}/10\n\n"
        f"<i>Targeting institutional liquidity sweep...</i>"
    )
    return msg

def format_exit_alert(symbol, result, pnl, total_pnl):
    """
    Formats a trade exit alert.
    """
    emoji = "✅" if pnl > 0 else "❌"
    msg = (
        f"<b>{emoji} Aurum Edge Trade Closed</b>\n\n"
        f"<b>Symbol:</b> {symbol.replace('=X', '')}\n"
        f"<b>Outcome:</b> {result}\n"
        f"<b>P&L:</b> ${pnl:.2f}\n"
        f"<b>Daily Running P&L:</b> ${total_pnl:.2f}"
    )
    return msg

def format_status_alert(status_msg):
    """
    Formats a system status alert.
    """
    return f"<b>🛡️ Aurum Edge Watchdog</b>\n\n{status_msg}"

def format_setup_alert(symbol, setup_type, target_price, score):
    """
    Formats a potential setup alert.
    """
    emoji = "🔍"
    msg = (
        f"<b>{emoji} Aurum Edge Setup Identified</b>\n\n"
        f"<b>Symbol:</b> {symbol.replace('=X', '')}\n"
        f"<b>Potential Action:</b> {setup_type.upper()}\n"
        f"<b>Sniper Entry Target:</b> {target_price:.5f}\n"
        f"<b>ML Conviction:</b> {score}/10\n\n"
        f"<i>BOS Confirmed. Awaiting retracement to Order Block mean...</i>"
    )
    return msg

if __name__ == "__main__":
    # Mock test
    import os
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        print("Sending test message...")
        send_telegram_message("🤖 Aurum Edge Utility Test: OK")
    else:
        print("Telegram not configured. Skipping mock test.")
