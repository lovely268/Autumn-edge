import os
import oandapyV20
import oandapyV20.endpoints.accounts as accounts

def list_accounts():
    api_key = os.getenv("OANDA_API_KEY")
    client = oandapyV20.API(access_token=api_key, environment="live")
    
    try:
        r = accounts.AccountList()
        client.request(r)
        print(r.response)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_accounts()
