import yfinance as yf
tickers = ["GB10Y.F", "JG10Y.F", "^TNX", "^GUK10", "GUK10.L"]
for t in tickers:
    data = yf.download(t, period="1mo")
    if not data.empty:
        print(f"Ticker {t} SUCCESS:")
        print(data.tail(1))
    else:
        print(f"Ticker {t} FAILED")
