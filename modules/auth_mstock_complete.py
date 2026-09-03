"""
=============================================================
M-STOCK Type B - COMPLETE Authentication (One Script)
=============================================================
Flow:
  1. Generate TOTP
  2. POST /connect/login  → get jwtToken (valid ~15 min)
  3. Test with fund summary

Run this fresh each time you need to get a token.
=============================================================
"""
import requests, json, pyotp, time, uuid, sys, base64
from datetime import datetime

API_KEY = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="
CLIENT_CODE = "MA1116489"
PASSWORD = "RAJ123RAJ@r2"
TOTP_SECRET = "YV6B24K7VV4VTDWJWX5CAYCDIUQ4GKVG"
CONFIG_PATH = "data/config.json"

BASE = "https://api.mstock.trade"

def fresh_totp():
    return pyotp.TOTP(TOTP_SECRET).now()

def check_expiry(token):
    try:
        parts = token.split(".")
        payload = base64.b64decode(parts[1] + "==").decode()
        data = json.loads(payload)
        exp = data.get("exp", 0)
        iat = data.get("iat", 0)
        now = time.time()
        print(f"    Token issued: {time.strftime('%H:%M:%S', time.localtime(iat))}")
        print(f"    Token expires: {time.strftime('%H:%M:%S', time.localtime(exp))}")
        print(f"    Valid for: {max(0, exp - now):.0f} seconds")
        return exp > now
    except Exception as e:
        print(f"    Could not check expiry: {e}")
        return False

def api(method, path, data=None, headers=None):
    url = BASE + path
    h = {"X-Mirae-Version": "1", "X-PrivateKey": API_KEY, "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = requests.request(method, url, json=data, headers=h, timeout=20)
    return r.status_code, r.text

print("=" * 60)
print("  M-STOCK - COMPLETE AUTHENTICATION")
print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("=" * 60)

# ================================================================
# STEP 1: Login with TOTP
# ================================================================
print("\n[1] Logging in with TOTP...")
totp = fresh_totp()
state = str(uuid.uuid4())
print(f"    TOTP: {totp}  |  State: {state[:8]}...")

login_data = {
    "clientcode": CLIENT_CODE,
    "password": PASSWORD,
    "totp": totp,
    "state": state
}

status, text = api("POST", "/openapi/typeb/connect/login", data=login_data)
print(f"    Login: {status}")

if status != 200:
    print(f"    FAILED: {text[:200]}")
    sys.exit(1)

resp = json.loads(text)
if not resp.get("status"):
    print(f"    Error: {resp.get('message', resp)}")
    sys.exit(1)

jwt_token = resp["data"].get("jwtToken") or resp["data"].get("jwt_token")
refresh_token = resp["data"].get("refreshToken") or resp["data"].get("refresh_token")

if not jwt_token:
    print(f"    No jwtToken in response: {resp}")
    sys.exit(1)

print(f"    Got jwtToken!")
check_expiry(jwt_token)

# Save to config
cfg = json.load(open(CONFIG_PATH))
cfg["access_token"] = jwt_token
cfg["refresh_token"] = refresh_token or ""
cfg["token_time"] = datetime.now().isoformat()
json.dump(cfg, open(CONFIG_PATH, "w"), indent=4)
print("    Saved to config.json")

# ================================================================
# STEP 2: Test with Bearer auth
# ================================================================
print("\n[2] Testing Bearer auth...")
status, text = api("GET", "/openapi/typeb/user/fundsummary",
    headers={"Authorization": f"Bearer {jwt_token}"})
print(f"    Bearer: {status} | {text[:150]}")

# ================================================================
# STEP 3: Test with api_key:jwtToken auth
# ================================================================
print("\n[3] Testing api_key:jwtToken auth...")
status, text = api("GET", "/openapi/typeb/user/fundsummary",
    headers={"Authorization": f"{API_KEY}:{jwt_token}"})
print(f"    api_key:jwtToken: {status} | {text[:150]}")

# ================================================================
# STEP 4: Try other endpoints
# ================================================================
print("\n[4] Testing other endpoints...")
endpoints = [
    ("GET", "/openapi/typeb/portfolio/holdings"),
    ("GET", "/openapi/typeb/orders"),
    ("GET", "/openapi/typeb/trades"),
]
for method, path in endpoints:
    status, text = api(method, path,
        headers={"Authorization": f"Bearer {jwt_token}"})
    short = path.split("openapi/")[-1]
    print(f"    {method} {short}: {status} | {text[:100]}")
