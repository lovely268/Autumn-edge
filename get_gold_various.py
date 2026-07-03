import os
import oandapyV20
import oandapyV20.endpoints.pricing as pricing

def get_gold_various():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    client = oandapyV20.API(access_token=api_key, environment="live")
    
    params = {"instruments": "XAU_USD,XAU_EUR,XAU_GBP"}
    try:
        r = pricing.PricingInfo(accountID=account_id, params=params)
        client.request(r)
        for p in r.response['prices']:
            print(f"{p['instrument']}: {p['bids'][0]['price']} | Status: {p['status']}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_gold_various()
