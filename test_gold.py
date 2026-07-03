import yfinance as yf
symbols = ["XAUUSD=X", "GC=F"]
for s in symbols:
    data = yf.download(s, period="1d")
    print(f"Symbol: {s}, Data: {not data.empty}")
