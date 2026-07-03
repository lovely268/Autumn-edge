import os
from oandapyV20 import API
import oandapyV20.endpoints.accounts as accounts

api_key = os.getenv("OANDA_API_KEY")
account_id = os.getenv("OANDA_ACCOUNT_ID")
env = os.getenv("OANDA_ENV", "live").lower()

client = API(access_token=api_key, environment=env)
r = accounts.AccountInstruments(accountID=account_id, params={"instruments": "XAU_USD"})

try:
    resp = client.request(r)
    inst = resp['instruments'][0]
    margin_rate = inst.get('marginRate', 'Unknown')
    print(f"Instrument: {inst['name']}")
    print(f"Margin Rate: {margin_rate}")
    
    # Calculate required margin for 1 unit
    # Margin = Price * MarginRate
    # Price is roughly 4086
    if margin_rate != 'Unknown':
        price = 4086
        required_margin = price * float(margin_rate)
        print(f"Required Margin for 1 unit: ${required_margin:.2f}")
except Exception as e:
    print(f"Error: {e}")
