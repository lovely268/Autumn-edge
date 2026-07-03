import yfinance as yf
tickers = ["^GUK10", "^GJGB10", "GB10Y-GB", "JP10Y-GB"]
for t in tickers:
    data = yf.download(t, period="1d")
    print(f"Ticker {t}:")
    print(data)
