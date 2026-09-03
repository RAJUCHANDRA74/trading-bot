"""Download NSE Bank Nifty daily OHLC data and save to CSV."""
import yfinance as yf
import csv
import os

print("Downloading NSE Bank Nifty daily data (6 months)...")
data = yf.download("^NSEBANK", period="6mo", interval="1d", progress=False)
print(f"Downloaded: {len(data)} rows")

# Flatten multi-index columns (level 1 = ticker, level 0 = OHLCV name)
# Columns are: [('Close', '^NSEBANK'), ('High', '^NSEBANK'), ...]
# So droplevel(1) gives us: ['Close', 'High', 'Low', 'Open', 'Volume']
if hasattr(data.columns, 'droplevel'):
    data.columns = data.columns.droplevel(1)

print(f"Columns after flatten: {list(data.columns)}")

path = os.path.join(os.path.dirname(__file__), "..", "data", "nsebank_daily.csv")

with open(path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["date", "open", "high", "low", "close", "volume"])
    for i in range(len(data)):
        dt = data.index[i]
        row = data.iloc[i]
        writer.writerow([
            str(dt.date()),
            round(float(row["Open"]), 2),
            round(float(row["High"]), 2),
            round(float(row["Low"]), 2),
            round(float(row["Close"]), 2),
            int(float(row["Volume"]))
        ])

print(f"Saved {len(data)} rows to {path}")

# Stats
closes = [float(data.iloc[i]["Close"]) for i in range(len(data))]
opens = [float(data.iloc[i]["Open"]) for i in range(len(data))]
highs = [float(data.iloc[i]["High"]) for i in range(len(data))]
lows = [float(data.iloc[i]["Low"]) for i in range(len(data))]
bullish = sum(1 for i in range(len(data)) if closes[i] > opens[i])
bearish = sum(1 for i in range(len(data)) if closes[i] < opens[i])
first_close = closes[0]
last_close = closes[-1]
net_move = last_close - first_close
net_pct = (net_move / first_close) * 100

print(f"\nData Summary (6 months):")
print(f"  Bullish days: {bullish}")
print(f"  Bearish days: {bearish}")
print(f"  Flat days: {len(data) - bullish - bearish}")
print(f"  Net move: {net_move:.2f} points ({net_pct:.2f}%)")
print(f"  High: {max(highs):.2f}, Low: {min(lows):.2f}")
print(f"  First: {first_close:.2f}, Last: {last_close:.2f}")
