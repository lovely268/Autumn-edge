#!/usr/bin/env python3
"""
Aurum Edge — Railway Entry Point
Starts the webhook server on port 3000 for TradingView + Signal Trade App integration.
"""
import os
import sys

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Start webhook server
from webhook_server import main

if __name__ == "__main__":
    main()