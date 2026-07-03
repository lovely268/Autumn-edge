import os
import json
from oandapyV20 import API
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.pricing as pricing
from oandapyV20.exceptions import V20Error

def verify_gbp_jpy():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    env = os.getenv("OANDA_ENV", "practice").lower()
    instrument = "GBP_JPY"
    
    print(f"Connecting to Oanda {env} account: {account_id}...")
    client = API(access_token=api_key, environment=env)
    
    try:
        # 1. Fetch Account Summary
        r = accounts.AccountSummary(account_id)
        response = client.request(r)
        account = response.get('account')
        balance = float(account.get('balance'))
        nav = float(account.get('NAV'))
        currency = account.get('currency')
        
        print(f"Connected. Balance: {balance} {currency}")
        
        # 2. Check if GBP_JPY is tradeable
        r = accounts.AccountInstruments(account_id)
        response = client.request(r)
        all_instruments = response.get('instruments', [])
        target = next((i for i in all_instruments if i['name'] == instrument), None)
        
        if not target:
            print(f"FAILED: {instrument} is NOT tradeable on this account.")
            return

        margin_rate = float(target.get('marginRate', 0))
        print(f"SUCCESS: {instrument} is tradeable.")
        print(f"Margin Rate: {margin_rate} (1:{int(1/margin_rate)} leverage)")
        
        # 3. Check margin for 1 unit
        r = pricing.PricingInfo(account_id, params={"instruments": instrument})
        response = client.request(r)
        price = float(response['prices'][0]['asks'][0]['price'])
        
        # Margin for GBP_JPY on a USD account:
        # Margin = Units * BasePrice * MarginRate (if base is account currency)
        # Or more accurately for Oanda: Margin = Units * (Current Price of Base CCY in Account CCY) * MarginRate
        # For GBP_JPY on USD account, we need GBP_USD price.
        
        # Oanda simplified: Margin = (Units * Price) / Leverage (in account currency)
        # Since JPY is quote, 1 unit of GBP_JPY = 1 GBP.
        # We need GBP_USD to calculate margin in USD.
        
        r_base = pricing.PricingInfo(account_id, params={"instruments": "GBP_USD"})
        res_base = client.request(r_base)
        gbp_usd_price = float(res_base['prices'][0]['asks'][0]['price'])
        
        margin_required_for_1_unit = 1 * gbp_usd_price * margin_rate
        print(f"Current GBP_JPY Ask Price: {price}")
        print(f"Current GBP_USD Price: {gbp_usd_price}")
        print(f"Margin Required for 1 unit (1 GBP): {margin_required_for_1_unit:.4f} USD")
        
        if nav >= margin_required_for_1_unit:
            print(f"RESULT: Account HAS sufficient funds for at least 1 unit of GBP_JPY.")
            max_units = int(nav / (gbp_usd_price * margin_rate))
            print(f"Max units possible with current NAV: {max_units}")
        else:
            print(f"RESULT: Account DOES NOT have sufficient funds for 1 unit of GBP_JPY.")
            
    except V20Error as e:
        print(f"FAILED: Oanda API Error: {e}")
    except Exception as e:
        print(f"FAILED: General Error: {e}")

if __name__ == "__main__":
    verify_gbp_jpy()
