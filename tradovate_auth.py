"""
Tradovate API Authentication Module
Handles token management, refresh, and session lifecycle for Tradovate REST & WebSocket APIs.
"""
import os
import time
import json
import requests

TRADOVATE_API_URL = "https://live.tradovateapi.com"
TRADOVATE_WS_URL = "wss://live.tradovateapi.com"

class TradovateAuth:
    def __init__(self):
        self.name = os.getenv("TRADOVATE_USERNAME", "")
        self.password = os.getenv("TRADOVATE_PASSWORD", "")
        self.app_id = "AurumEdge"
        self.app_version = "1.0"
        self.cid = 0
        self.secret = ""
        self.access_token = None
        self.token_expiry = 0
        self.md_token = None
        self.md_token_expiry = 0

    def _save_credentials(self, token_data):
        """Persist token data to file for reuse across restarts."""
        cred_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tradovate_creds")
        with open(cred_path, "w") as f:
            json.dump(token_data, f)

    def _load_credentials(self):
        """Load persisted token data."""
        cred_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tradovate_creds")
        if os.path.exists(cred_path):
            with open(cred_path, "r") as f:
                return json.load(f)
        return None

    def authenticate(self):
        """Full authentication flow: token fetch or refresh."""
        if self.access_token and time.time() < self.token_expiry - 60:
            return self.access_token

        # Try refresh first
        creds = self._load_credentials()
        if creds and creds.get("refresh_token"):
            refreshed = self._refresh_access_token(creds["refresh_token"])
            if refreshed:
                return self.access_token

        # Full login
        return self._full_login()

    def _full_login(self):
        """Login with username/password credentials."""
        payload = {
            "name": self.name,
            "password": self.password,
            "appId": self.app_id,
            "appVersion": self.app_version,
            "cid": self.cid if self.cid > 0 else "",
            "sec": self.secret
        }
        try:
            resp = requests.post(
                f"{TRADOVATE_API_URL}/auth/accesstoken/request",
                json=payload,
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get("accessToken")
                expires_in = data.get("expireTime", 86400)
                self.token_expiry = time.time() + expires_in
                self._save_credentials(data)
                print("[TRADOVATE AUTH] Authentication successful.", flush=True)
                return self.access_token
            else:
                print(f"[TRADOVATE AUTH] Login failed: {resp.status_code} {resp.text}", flush=True)
                return None
        except Exception as e:
            print(f"[TRADOVATE AUTH] Login error: {e}", flush=True)
            return None

    def _refresh_access_token(self, refresh_token):
        """Refresh access token using refresh token."""
        payload = {"refreshToken": refresh_token}
        try:
            resp = requests.post(
                f"{TRADOVATE_API_URL}/auth/accesstoken/refresh",
                json=payload,
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get("accessToken")
                expires_in = data.get("expireTime", 86400)
                self.token_expiry = time.time() + expires_in
                self._save_credentials(data)
                print("[TRADOVATE AUTH] Token refreshed successfully.", flush=True)
                return self.access_token
            return None
        except Exception as e:
            print(f"[TRADOVATE AUTH] Refresh error: {e}", flush=True)
            return None

    def get_md_token(self):
        """Get a market data access token (separate from regular access token)."""
        if self.md_token and time.time() < self.md_token_expiry - 60:
            return self.md_token

        token = self.authenticate()
        if not token:
            return None

        try:
            resp = requests.get(
                f"{TRADOVATE_API_URL}/auth/accesstoken/md",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                self.md_token = data.get("accessToken")
                expires_in = data.get("expireTime", 86400)
                self.md_token_expiry = time.time() + expires_in
                return self.md_token
            else:
                print(f"[TRADOVATE AUTH] MD token fetch failed: {resp.status_code}", flush=True)
                return None
        except Exception as e:
            print(f"[TRADOVATE AUTH] MD token error: {e}", flush=True)
            return None