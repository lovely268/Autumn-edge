import yfinance as yf
import pandas as pd

SYMBOLS = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "USDCAD=X", "AUDUSD=X", "NZDUSD=X",
    "EURGBP=X", "EURJPY=X", "EURCHF=X", "EURCAD=X", "EURAUD=X", "EURNZD=X",
    "GBPJPY=X", "GBPCHF=X", "GBPCAD=X", "GBPAUD=X", "GBPNZD=X",
    "AUDJPY=X", "AUDCHF=X", "AUDCAD=X", "AUDNZD=X",
    "NZDJPY=X", "NZDCHF=X", "NZDCAD=X",
    "CADJPY=X", "CADCHF=X", "CHFJPY=X",
    "GC=F"
]

def validate_symbols():
    print(f"{'Symbol':<15} | {'Status':<10} | {'Latest Price':<10}")
    print("-" * 40)
    for symbol in SYMBOLS:
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d")
            if data.empty:
                print(f"{symbol:<15} | FAILED     | N/A")
            else:
                price = data['Close'].iloc[-1]
                print(f"{symbol:<15} | OK         | {price:.4f}")
        except Exception as e:
            print(f"{symbol:<15} | ERROR      | {str(e)}")

if __name__ == "__main__":
    validate_symbols()
