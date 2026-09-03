"""
=============================================================
Fetch Bank Nifty futures data from MULTIPLE contract months
and chain them together for continuous backtesting.
=============================================================
Available contracts:
  BANKNIFTY26AUGFUT  (exp: 27Aug2026, token: ?)
  BANKNIFTY26SEPFUT  (exp: 29Sep2026, token: 68390)  ← current
  BANKNIFTY26OCTFUT  (exp: 27Oct2026, token: 48699)
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
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "banknifty_historical.csv")

TOKEN = "68390"    # BANKNIFTY26SEPFUT
TOKEN_AUG = "???"  # BANKNIFTY26AUGFUT - need to find
TOKEN_OCT = "48699"  # BANKNIFTY26OCTFUT
EXCHANGE = "NFO"
INTERVAL = "FIFTEEN_MINUTE"


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
    raise RuntimeError("Could not connect")


def fetch_candles(m, token, start_date, end_date):
    """Fetch candles for a specific token and date range."""
    all_candles = []
    chunk_days = 15
    current = start_date

    while current < end_date:
        chunk_end = min(current + timedelta(days=chunk_days), end_date)
        print(f"  Token {token}: {current.strftime('%Y-%m-%d')} -> {chunk_end.strftime('%Y-%m-%d')}")

        for retry in range(5):
            try:
                result = m.get_historical_chart(
                    _exchange=EXCHANGE,
                    _security_token=token,
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
                        print(f"    No candles")
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


def main():
    print("=" * 60)
    print("  CHAINING MULTIPLE FUTURES CONTRACT MONTHS")
    print("=" * 60)

    print("\n[1] Finding all Bank Nifty futures tokens...")
    m = connect()

    # Get instrument list to find AUG contract token
    print("\n  Searching for BANKNIFTY futures tokens...")
    result = m.get_instruments()
    instruments = result.json()

    bn_futures = [i for i in instruments
                  if "BANKNIFTY" in i.get("symbol", "")
                  and "FUT" in i.get("name", "")
                  and i.get("exch_seg") == "NFO"]
    bn_futures.sort(key=lambda x: x.get("expiry", ""))
    print(f"  Found {len(bn_futures)} futures contracts:")
    for i in bn_futures:
        print(f"    Token={i['token']}  Symbol={i['symbol']}  Expiry={i['expiry']}  Lot={i['lotsize']}")

    if not bn_futures:
        print("  No futures contracts found!")
        return

    # Pick the 3 most recent contracts
    contracts = bn_futures[-3:]
    print(f"\n  Using 3 contracts: {[c['token'] for c in contracts]}")

    # Date range: go back 180 days from now
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)

    # Fetch data from each contract
    all_candles = []
    for contract in contracts:
        token = contract["token"]
        expiry = contract["expiry"]
        print(f"\n[2] Fetching {expiry} (token: {token})...")

        # Each contract has ~60 days of history
        # Fetch from start_date to the contract expiry
        contract_end = datetime.strptime(expiry, "%d%b%Y") + timedelta(days=1)
        contract_end = min(contract_end, end_date)

        candles = fetch_candles(m, token, start_date, contract_end)
        print(f"    Total from this contract: {len(candles)} candles")

        if candles:
            all_candles.extend(candles)
            # Don't fetch the same date range for next contract
            # The next contract's history should overlap, so we'll dedupe

    if not all_candles:
        print("\n  ERROR: No candles fetched!")
        return

    # Sort and dedupe by datetime
    all_candles.sort(key=lambda x: x[0])
    unique = []
    seen = set()
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)
    all_candles = unique

    first = all_candles[0]
    last = all_candles[-1]
    print(f"\n  Total unique candles: {len(all_candles)}")
    print(f"  Range: {first[0]} -> {last[0]}")
    print(f"  Days: {(datetime.fromisoformat(last[0].replace(' ', 'T')) - datetime.fromisoformat(first[0].replace(' ', 'T'))).days} days")

    # Save
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for c in all_candles:
            if len(c) >= 5:
                writer.writerow([c[0], round(c[1], 2), round(c[2], 2),
                               round(c[3], 2), round(c[4], 2),
                               c[5] if len(c) > 5 else 0])

    print(f"\n  Saved to {OUTPUT_PATH}")
    print("\n  DONE!")


if __name__ == "__main__":
    main()
