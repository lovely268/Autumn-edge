import os
import sys
from telegram_notify import send_telegram_message, format_trade_alert, format_exit_alert, format_status_alert

def run_test():
    print("--- Aurum Edge Telegram Integration Mock Test ---")
    
    # 1. Check Configuration
    from config import TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    print(f"Telegram Enabled: {TELEGRAM_ENABLED}")
    if not TELEGRAM_ENABLED:
        print("ERROR: Telegram not enabled. Ensure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in environment.")
        # We can still test the formatting logic
    else:
        print(f"Chat ID: {TELEGRAM_CHAT_ID}")
        print(f"Bot Token (first 5 chars): {TELEGRAM_BOT_TOKEN[:5]}...")

    # 2. Test Formatting
    print("\nTesting formatting logic...")
    
    entry_msg = format_trade_alert("EURUSD=X", "long", 1.12345, 1.12000, 1.13000, 8.5)
    print("\n--- Entry Alert ---")
    print(entry_msg)
    
    exit_msg = format_exit_alert("EURUSD=X", "TP Hit: TP1 (1.5:1)", 15.20, 45.50)
    print("\n--- Exit Alert ---")
    print(exit_msg)
    
    status_msg = format_status_alert("⚠️ <b>Service Failure:</b> pipeline_service.py is not running. Attempting automatic restart...")
    print("\n--- Status Alert ---")
    print(status_msg)

    # 3. Try sending if enabled
    if TELEGRAM_ENABLED:
        print("\nSending test alerts to Telegram...")
        try:
            send_telegram_message("🤖 <b>Aurum Edge:</b> Integration Test Sequence Started.")
            send_telegram_message(entry_msg)
            send_telegram_message(exit_msg)
            send_telegram_message(status_msg)
            send_telegram_message("🤖 <b>Aurum Edge:</b> Integration Test Sequence Completed.")
            print("Done. Check your Telegram chat.")
        except Exception as e:
            print(f"Failed to send: {e}")
    else:
        print("\nTelegram not configured. Skipping send test.")

if __name__ == "__main__":
    run_test()
