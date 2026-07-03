import os
import oandapyV20
import oandapyV20.endpoints.pricing as pricing

def get_gold_price():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    client = oandapyV20.API(access_token=api_key, environment="live")
    
    params = {"instruments": "XAU_USD"}
    try:
        r = pricing.PricingInfo(accountID=account_id, params=params)
        client.request(r)
        print(r.response)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_gold_price()
