"""
=============================================================
Fetch 15-minute historical candles for BANKNIFTY futures
from M-Stock API and save to CSV.
=============================================================
"""
from tradingapi_b.mconnect import MConnectB
import pyotp, json, csv, time
from datetime import datetime, timedelta
import os

API_KEY = "06SomqZj4ZsvaWc0se3gc0Y1OFbpAIj6CS8W8tQTI/M="
CLIENT_CODE = "MA1116489"
PASSWORD = "RAJ123RAJ@r2"
TOTP_SECRET = "YV6B24K7VV4VTDWJWX5CAYCDIUQ4GKVG"

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "banknifty_15min.csv")

# Bank Nifty September futures
TOKEN = "68390"
EXCHANGE = "NFO"
INTERVAL = "FIFTEEN_MINUTE"
DAYS_BACK = 60  # Last 60 trading days


def connect():
    """Connect to M-Stock."""
    m = MConnectB()
    m.set_api_key(API_KEY)
    lr = m.login(CLIENT_CODE, PASSWORD)
    rt = lr.json()["data"]["refreshToken"]
    m.verify_totp(API_KEY, rt, pyotp.TOTP(TOTP_SECRET).now())
    return m


def fetch_candles(m, start_date: datetime, end_date: datetime) -> list:
    """
    Fetch 15-minute candles in chunks (API has a limit per request).
    Returns list of candles [timestamp, open, high, low, close, volume].
    """
    all_candles = []
    chunk_days = 15  # Fetch 15 days at a time

    current = start_date
    while current < end_date:
        chunk_end = min(current + timedelta(days=chunk_days), end_date)
        print(f"  Fetching: {current.strftime('%Y-%m-%d')} -> {chunk_end.strftime('%Y-%m-%d')}")

        result = m.get_historical_chart(
            _exchange=EXCHANGE,
            _security_token=TOKEN,
            _interval=INTERVAL,
            _fromDate=current.strftime("%Y-%m-%d %H:%M:%S"),
            _toDate=chunk_end.strftime("%Y-%m-%d %H:%M:%S")
        )
        data = result.json()
        if data.get("status"):
            candles = data.get("data", {}).get("candles", [])
            if candles:
                all_candles.extend(candles)
                print(f"    Got {len(candles)} candles")
            else:
                print(f"    No candles in this range")
        else:
            print(f"    Error: {data.get('message')}")

        current = chunk_end
        time.sleep(0.3)  # Be polite to the API

    return all_candles


def save_to_csv(candles: list, path: str):
    """Save candles to CSV."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for c in candles:
            # Candle format: [timestamp, open, high, low, close, volume]
            if len(c) >= 5:
                writer.writerow([
                    c[0],  # datetime string
                    round(c[1], 2),  # open
                    round(c[2], 2),  # high
                    round(c[3], 2),  # low
                    round(c[4], 2),  # close
                    c[5] if len(c) > 5 else 0  # volume
                ])
    print(f"\n  Saved {len(candles)} candles to {path}")


def main():
    print("=" * 60)
    print("  FETCHING 15-MINUTE BANK NIFTY DATA FROM M-STOCK")
    print("=" * 60)

    # Date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_BACK)
    print(f"\n  Date range: {start_date.strftime('%Y-%m-%d')} -> {end_date.strftime('%Y-%m-%d')}")
    print(f"  Exchange: {EXCHANGE}, Token: {TOKEN}")
    print(f"  Interval: {INTERVAL}")

    # Connect
    print("\n[1] Connecting to M-Stock...")
    m = connect()
    print("    Connected!")

    # Fetch
    print("\n[2] Fetching candles...")
    candles = fetch_candles(m, start_date, end_date)

    if not candles:
        print("\n  ERROR: No candles fetched!")
        return

    print(f"\n  Total candles: {len(candles)}")

    # Show range
    first = candles[0]
    last = candles[-1]
    print(f"  Date range: {first[0]} -> {last[0]}")

    # Show sample
    print("\n  Sample candles:")
    for c in candles[:3]:
        print(f"    {c[0]}: O={c[1]:.2f} H={c[2]:.2f} L={c[3]:.2f} C={c[4]:.2f}")

    # Save
    print("\n[3] Saving to CSV...")
    save_to_csv(candles, OUTPUT_PATH)

    print("\n" + "=" * 60)
    print("  DATA FETCH COMPLETE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
