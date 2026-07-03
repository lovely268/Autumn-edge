import os
import oandapyV20
import oandapyV20.endpoints.accounts as accounts

def list_all():
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    client = oandapyV20.API(access_token=api_key, environment="live")
    
    try:
        r = accounts.AccountInstruments(accountID=account_id)
        client.request(r)
        instruments = r.response.get('instruments', [])
        for inst in instruments:
            print(f"{inst['name']} | {inst['type']} | MinUnit: {inst.get('minimumTradeUnit')} | Margin: {inst.get('marginRate')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_all()
