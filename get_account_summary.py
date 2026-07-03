import os
import oandapyV20
import oandapyV20.endpoints.accounts as accounts

def get_account_summary():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    client = oandapyV20.API(access_token=api_key, environment="live")
    
    try:
        r = accounts.AccountSummary(accountID=account_id)
        client.request(r)
        print(r.response)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_account_summary()
