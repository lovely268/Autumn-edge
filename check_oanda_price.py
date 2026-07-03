import os
from oandapyV20 import API
from oandapyV20.endpoints.pricing import PricingInfo

api_key = os.getenv("OANDA_API_KEY")
account_id = os.getenv("OANDA_ACCOUNT_ID")
env = os.getenv("OANDA_ENV", "live").lower()

if not api_key or not account_id:
    print("API Key or Account ID missing")
    exit(1)

client = API(access_token=api_key, environment=env)
params = {"instruments": "XAU_USD"}
r = PricingInfo(account_id, params=params)

try:
    resp = client.request(r)
    price = resp['prices'][0]
    bid = price['bids'][0]['price']
    ask = price['asks'][0]['price']
    print(f"XAU_USD - Bid: {bid}, Ask: {ask}")
except Exception as e:
    print(f"Error: {e}")
