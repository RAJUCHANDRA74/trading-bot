"""
=============================================================
M-STOCK Type B - Complete TOTP Authentication Flow
=============================================================
Step 1: POST /openapi/typeb/connect/login  → get requestToken
Step 2: POST /openapi/typeb/session/token  → requestToken + OTP/TOTP → accessToken

NOTE: If SMS OTP works for you, use Step 2a with SMS.
      If SMS doesn't arrive (like Rajkumar), use Step 2b with TOTP.
=============================================================
"""

import requests, json, pyotp, time, sys
from datetime import datetime

API_KEY = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="
CLIENT_CODE = "MA1116489"
PASSWORD = "RAJ123RAJ@r2"
TOTP_SECRET = "YV6B24K7VV4VTDWJWX5CAYCDIUQ4GKVG"
CONFIG_PATH = "data/config.json"

BASE = "https://api.mstock.trade"
HEADERS = {
    "X-Mirae-Version": "1",
    "Content-Type": "application/json",
    "X-PrivateKey": API_KEY
}

def save_config(data):
    cfg = json.load(open(CONFIG_PATH))
    cfg.update(data)
    json.dump(cfg, open(CONFIG_PATH, "w"), indent=4)

def api_call(method, path, data=None, headers=None, desc=""):
    url = BASE + path
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    try:
        if method == "POST":
            r = requests.post(url, json=data, headers=h, timeout=20)
        else:
            r = requests.get(url, headers=h, timeout=20)
        try:
            j = r.json()
            j_str = json.dumps(j, ensure_ascii=False)[:300]
            print(f"  [{desc}] {method} {path} -> {r.status_code} | {j_str}")
            return j
        except Exception:
            try:
                print(f"  [{desc}] {method} {path} -> {r.status_code} | {r.text[:200]}")
            except Exception:
                print(f"  [{desc}] {method} {path} -> {r.status_code}")
            return None
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

print("=" * 60)
print("  M-STOCK Type B - TOTP AUTHENTICATION")
print("=" * 60)
print(f"  Time: {datetime.now().strftime('%H:%M:%S')}")
print()

# ================================================================
# STEP 1: Login → Get requestToken (this also sends SMS OTP)
# ================================================================
print("[STEP 1] Logging in to get requestToken...")
login_data = {
    "clientcode": CLIENT_CODE,
    "password": PASSWORD
}
result = api_call("POST", "/openapi/typeb/connect/login", login_data, desc="LOGIN")

if not result:
    print("\n  FATAL: Login endpoint failed completely.")
    print("  The API may be down or the credentials are wrong.")
    sys.exit(1)

# Check response
if result.get("status") == "error" and "expired" in str(result.get("message", "")).lower():
    print("\n  FATAL: API subscription is expired or suspended (IA403).")
    print("  Please renew at: https://trade.mstock.com")
    sys.exit(1)

# Extract requestToken
request_token = None
if result.get("status") == True:
    # Success - OTP sent
    data = result.get("data", {})
    if isinstance(data, list) and len(data) > 0:
        request_token = data[0].get("requestToken") or data[0].get("request_token")
    elif isinstance(data, dict):
        request_token = data.get("requestToken") or data.get("request_token")
    
    if request_token:
        print(f"\n  ✓ Login successful! RequestToken: {request_token[:30]}...")
        print(f"  ✓ SMS OTP sent to your phone (if enabled)")
    else:
        print(f"\n  Login response: {result}")
        request_token = result.get("requestToken") or result.get("request_token")

elif result.get("status") == "error":
    msg = result.get("message", "")
    print(f"\n  Login error: {msg}")
    if "expired" in msg.lower() or "suspended" in msg.lower():
        print("  → API subscription issue. Login to trade.mstock.com to renew.")
    sys.exit(1)
else:
    print(f"\n  Unexpected response: {result}")
    # Try to find requestToken anywhere in response
    request_token = result.get("requestToken") or result.get("request_token")

if not request_token:
    print("\n  Could not extract requestToken from login response.")
    print(f"  Full response: {result}")
    sys.exit(1)

print(f"\n  RequestToken: {request_token}")

# ================================================================
# STEP 2a: Generate session with TOTP (since SMS OTP doesn't work)
# ================================================================
print()
print("[STEP 2] Generating session with TOTP...")

# Generate TOTP
totp_code = pyotp.TOTP(TOTP_SECRET).now()
print(f"  TOTP: {totp_code}")

# Try the TOTP verify endpoint
session_data = {
    "request_token": request_token,
    "totp": totp_code
}

result = api_call(
    "POST",
    "/openapi/typeb/session/verifytotp",
    session_data,
    desc="TOTP_VERIFY"
)

if result and result.get("status") == True:
    data = result.get("data", [])
    if isinstance(data, list) and len(data) > 0:
        d = data[0]
        access_token = d.get("accessToken") or d.get("access_token")
        refresh_token = d.get("refreshToken") or d.get("refresh_token")
        enctoken = d.get("enctoken") or d.get("encToken")
        
        if access_token:
            print(f"\n  ✓ ACCESS TOKEN: {access_token[:40]}...")
            print(f"  ✓ REFRESH TOKEN: {refresh_token[:40] if refresh_token else 'N/A'}...")
            
            # Save to config
            save_config({
                "access_token": access_token,
                "refresh_token": refresh_token,
                "enctoken": enctoken,
                "request_token": request_token,
                "token_time": datetime.now().isoformat()
            })
            print("\n  ✓ Tokens saved to data/config.json")
            
            # Test the token immediately
            print()
            print("[VERIFY] Testing token with fund summary...")
            test = api_call(
                "GET",
                "/openapi/typeb/user/fundsummary",
                headers={"Authorization": f"Bearer {access_token}"},
                desc="VERIFY"
            )
            if test and test.get("status") == True:
                print()
                print("=" * 60)
                print("  🎉 M-STOCK CONNECTED SUCCESSFULLY!")
                print("=" * 60)
                funds = test.get("data", [{}])[0] if test.get("data") else {}
                print(f"  Available Balance: ₹{funds.get('AVAILABLE_BALANCE', 'N/A')}")
                print(f"  Clear Balance: ₹{funds.get('CLEAR_BALANCE', 'N/A')}")
            else:
                print("\n  Token saved but API test failed.")
                print(f"  Response: {test}")
        else:
            print(f"\n  No access token in response: {result}")
    else:
        print(f"  Unexpected data format: {result}")
else:
    print(f"\n  TOTP verify failed: {result}")
    print()
    print("  Trying alternative endpoint...")
    
    # Try without 'openapi/typeb' duplication in path
    result2 = api_call(
        "POST",
        "/openapi/typeb/openapi/typeb/session/verifytotp",
        session_data,
        desc="TOTP_V2"
    )
    if result2 and result2.get("status") == True:
        print("  ✓ Alternative endpoint worked!")
        data = result2.get("data", [{}])[0]
        access_token = data.get("accessToken") or data.get("access_token")
        if access_token:
            save_config({"access_token": access_token, "token_time": datetime.now().isoformat()})
            print("  ✓ Token saved!")
