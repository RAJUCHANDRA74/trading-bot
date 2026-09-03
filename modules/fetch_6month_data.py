"""
=============================================================
Fetch 6 months of 15-minute Bank Nifty data from M-Stock.
=============================================================
"""
from tradingapi_b.mconnect import MConnectB
import pyotp, csv, time
from datetime import datetime, timedelta
import os, sys

API_KEY = "06SomqZj4ZsvaWc0se3gc0Y1OFbpAIj6CS8W8tQTI/M="
CLIENT_CODE = "MA1116489"
PASSWORD = "RAJ123RAJ@r2"
TOTP_SECRET = "YV6B24K7VV4VTDWJWX5CAYCDIUQ4GKVG"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "banknifty_6month.csv")

TOKEN = "68390"
EXCHANGE = "NFO"
INTERVAL = "FIFTEEN_MINUTE"
DAYS_BACK = 180  # 6 months


def connect():
    m = MConnectB()
    m.set_api_key(API_KEY)
    for attempt in range(10):
        try:
            lr = m.login(CLIENT_CODE, PASSWORD)
            rt = lr.json()["data"]["refreshToken"]
            totp = pyotp.TOTP(TOTP_SECRET).now()
            vr = m.verify_totp(API_KEY, rt, totp)
            if vr.json().get("status"):
                print(f"    Connected (attempt {attempt+1})")
                return m
        except Exception as e:
            print(f"    Attempt {attempt+1} failed: {e}")
            time.sleep(3)
    raise RuntimeError("Could not connect to M-Stock")


def fetch_candles(m, start_date: datetime, end_date: datetime) -> list:
    all_candles = []
    chunk_days = 15

    current = start_date
    while current < end_date:
        chunk_end = min(current + timedelta(days=chunk_days), end_date)
        print(f"  Fetching: {current.strftime('%Y-%m-%d')} -> {chunk_end.strftime('%Y-%m-%d')}")

        for retry in range(5):
            try:
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
                        print(f"    Got {len(candles)} candles (total: {len(all_candles)})")
                    else:
                        print(f"    No candles in this range")
                    break
                else:
                    print(f"    Error: {data.get('message')}")
                    time.sleep(2)
            except Exception as e:
                print(f"    Retry {retry+1}: {e}")
                time.sleep(3)

        current = chunk_end
        time.sleep(0.5)

    return all_candles


def save_to_csv(candles: list, path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for c in candles:
            if len(c) >= 5:
                writer.writerow([
                    c[0],
                    round(c[1], 2),
                    round(c[2], 2),
                    round(c[3], 2),
                    round(c[4], 2),
                    c[5] if len(c) > 5 else 0
                ])
    print(f"\n  Saved {len(candles)} candles to {path}")


def main():
    print("=" * 60)
    print("  FETCHING 6 MONTHS OF 15-MIN DATA FROM M-STOCK")
    print("=" * 60)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_BACK)
    print(f"\n  Date range: {start_date.strftime('%Y-%m-%d')} -> {end_date.strftime('%Y-%m-%d')}")
    print(f"  Instrument: BANKNIFTY26SEPFUT (token: {TOKEN})")

    print("\n[1] Connecting to M-Stock...")
    m = connect()

    print("\n[2] Fetching candles (this will take a few minutes)...")
    candles = fetch_candles(m, start_date, end_date)

    if not candles:
        print("\n  ERROR: No candles fetched!")
        return

    # Sort and dedupe
    candles.sort(key=lambda x: x[0])
    unique = []
    seen = set()
    for c in candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)
    candles = unique

    first = candles[0]
    last = candles[-1]
    print(f"\n  Total: {len(candles)} candles")
    print(f"  Range: {first[0]} -> {last[0]}")
    print(f"\n  Sample:")
    for c in candles[:3]:
        print(f"    {c[0]}: O={c[1]:.2f} H={c[2]:.2f} L={c[3]:.2f} C={c[4]:.2f}")

    print("\n[3] Saving to CSV...")
    save_to_csv(candles, OUTPUT_PATH)
    print("\n  DONE!")


if __name__ == "__main__":
    main()
