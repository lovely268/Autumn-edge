import os
import oandapyV20
import oandapyV20.endpoints.accounts as accounts

def list_all_instruments():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    client = oandapyV20.API(access_token=api_key, environment="live")
    
    try:
        # Fixed keyword argument
        r = accounts.AccountInstruments(accountID=account_id)
        client.request(r)
        instruments = r.response.get('instruments', [])
        for inst in instruments:
            # Print everything just in case
            print(inst['name'])
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_all_instruments()
