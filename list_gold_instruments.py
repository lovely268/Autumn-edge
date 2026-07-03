import os
from oandapyV20 import API
import oandapyV20.endpoints.accounts as accounts

api_key = os.getenv("OANDA_API_KEY")
account_id = os.getenv("OANDA_ACCOUNT_ID")
env = os.getenv("OANDA_ENV", "live").lower()

client = API(access_token=api_key, environment=env)
r = accounts.AccountInstruments(accountID=account_id)

try:
    resp = client.request(r)
    instruments = resp['instruments']
    for inst in instruments:
        if "XAU" in inst['name'] or "GOLD" in inst['name'].upper():
            print(f"Name: {inst['name']}, Margin Rate: {inst.get('marginRate')}")
except Exception as e:
    print(f"Error: {e}")
