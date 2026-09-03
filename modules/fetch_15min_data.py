"""
=============================================================
Step 1: Connect to M-Stock and fetch 15-minute candle data
for Bank Nifty futures.
=============================================================
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))

from tradingapi_b.mconnect import MConnectB
import pyotp

# Credentials
API_KEY = "06SomqZj4ZsvaWc0se3gc0Y1OFbpAIj6CS8W8tQTI/M="
CLIENT_CODE = "MA1116489"
PASSWORD = "RAJ123RAJ@r2"
TOTP_SECRET = "YV6B24K7VV4VTDWJWX5CAYCDIUQ4GKVG"

print("=" * 60)
print("  PULLING 15-MINUTE HISTORICAL DATA FROM M-STOCK")
print("=" * 60)

# ── Connect ─────────────────────────────────────────────────
print("\n[1] Connecting to M-Stock...")
m = MConnectB()
m.set_api_key(API_KEY)

lr = m.login(CLIENT_CODE, PASSWORD)
ld = lr.json()
rt = ld["data"]["refreshToken"]
totp = pyotp.TOTP(TOTP_SECRET).now()
vr = m.verify_totp(API_KEY, rt, totp)
print("    Connected!")

# ── Find Bank Nifty instrument ───────────────────────────────
print("\n[2] Searching for Bank Nifty instrument...")
try:
    result = m.get_instruments(exchange="NSEFO", symbol="BANKNIFTY")
    if hasattr(result, 'json'):
        data = result.json()
    else:
        data = result
    print(f"    Response type: {type(data)}")
    print(f"    Data: {str(data)[:500]}")
except Exception as e:
    print(f"    Search failed: {e}")

# Try alternative search
print("\n[3] Trying exchange segments...")
try:
    result2 = m.get_instruments(exchange="NSEFO", symbol="BN")
    if hasattr(result2, 'json'):
        data2 = result2.json()
    else:
        data2 = result2
    print(f"    BN Response: {str(data2)[:500]}")
except Exception as e:
    print(f"    BN search failed: {e}")

# ── Try intraday chart ───────────────────────────────────────
print("\n[4] Trying intraday chart for Bank Nifty...")
from datetime import datetime, timedelta

end_date = datetime.now()
start_date = end_date - timedelta(days=30)

try:
    result3 = m.get_intraday_chart(
        exchange="NSEFO",
        symbol="BANKNIFTY",
        interval="15minute",
        from_date=start_date.strftime("%Y-%m-%d %H:%M"),
        to_date=end_date.strftime("%Y-%m-%d %H:%M")
    )
    if hasattr(result3, 'json'):
        data3 = result3.json()
    else:
        data3 = result3
    print(f"    Response: {str(data3)[:500]}")
except Exception as e:
    print(f"    Intraday chart failed: {e}")

print("\n[5] Done exploring. Let me check all available methods...")
methods = [m for m in dir(m) if not m.startswith('_') and 'instrument' in m.lower() or 'hist' in m.lower() or 'chart' in m.lower() or 'candle' in m.lower() or 'data' in m.lower() or 'quote' in m.lower()]
print(f"    Relevant methods: {methods}")
