import os
import json
import oandapyV20
import oandapyV20.endpoints.instruments as instruments

def get_sentiment(instrument="GBP_JPY"):
    api_key = os.getenv("OANDA_API_KEY")
    client = oandapyV20.API(access_token=api_key, environment="live")
    
    try:
        r = instruments.InstrumentsPositionBook(instrument=instrument)
        client.request(r)
        book = r.response.get('positionBook')
        if book:
            # print(json.dumps(book, indent=2))
            long_pos = float(book.get('longPercent', 0))
            short_pos = float(book.get('shortPercent', 0))
            print(f"Instrument: {instrument}")
            print(f"Long %: {long_pos}")
            print(f"Short %: {short_pos}")
            return long_pos, short_pos
    except Exception as e:
        print(f"Error: {e}")
    return None, None

if __name__ == "__main__":
    get_sentiment()
