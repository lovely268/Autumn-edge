import yfinance as yf
t = yf.Ticker("^GUK10")
print(t.history(period="5d"))
