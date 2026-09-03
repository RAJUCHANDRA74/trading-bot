"""
=============================================================
M-STOCK Type B - COMPLETE WORKING AUTHENTICATION
=============================================================
DISCOVERY: The correct base URL is https://mstock.trade/openapi
           (NOT https://api.mstock.trade/openapi)

Flow:
  1. Generate TOTP
  2. POST /typeb/connect/login  → get jwtToken (valid ~5 min)
  3. Use Bearer jwtToken for all API calls

=============================================================
"""
import requests, json, pyotp, time, uuid, sys, base64
from datetime import datetime

API_KEY = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="
CLIENT_CODE = "MA1116489"
PASSWORD = "RAJ123RAJ@r2"
TOTP_SECRET = "YV6B24K7VV4VTDWJWX5CAYCDIUQ4GKVG"
CONFIG_PATH = "data/config.json"

# CORRECT BASE URL (not api.mstock.trade!)
BASE = "https://mstock.trade/openapi"


def api(method, path, data=None, jwt=None):
    """Make an API call with the correct base URL and auth."""
    url = BASE + path
    headers = {
        "X-Mirae-Version": "1",
        "X-PrivateKey": API_KEY,
        "Content-Type": "application/json",
    }
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"

    r = requests.request(method, url, json=data, headers=headers, timeout=20)
    return r.status_code, r.text


def get_fresh_token():
    """Login with TOTP and get a fresh jwtToken."""
    totp = pyotp.TOTP(TOTP_SECRET).now()
    state = str(uuid.uuid4())

    print(f"    TOTP: {totp}  |  State: {state[:8]}...")
    status, text = api("POST", "/typeb/connect/login", data={
        "clientcode": CLIENT_CODE,
        "password": PASSWORD,
        "totp": totp,
        "state": state
    })

    if status != 200:
        print(f"    Login FAILED ({status}): {text[:200]}")
        return None

    resp = json.loads(text)
    if not resp.get("status"):
        print(f"    Error: {resp.get('message', resp)}")
        return None

    jwt = resp["data"].get("jwtToken")
    refresh = resp["data"].get("refreshToken")

    if not jwt:
        print(f"    No jwtToken in response!")
        return None

    # Show expiry
    try:
        parts = jwt.split(".")
        payload = json.loads(base64.b64decode(parts[1] + "==").decode())
        exp = payload.get("exp", 0)
        remaining = max(0, exp - time.time())
        print(f"    Token valid for: {remaining:.0f} seconds (~{remaining/60:.1f} min)")
    except Exception:
        pass

    return jwt, refresh


def main():
    print("=" * 60)
    print("  M-STOCK Type B - WORKING AUTHENTICATION")
    print("  Base: " + BASE)
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    # ================================================================
    # STEP 1: Get fresh token
    # ================================================================
    print("\n[1] Getting fresh TOTP token...")
    result = get_fresh_token()
    if not result:
        sys.exit(1)

    jwt_token, refresh_token = result
    print(f"    Got jwtToken: {jwt_token[:40]}...")

    # Save to config
    cfg = json.load(open(CONFIG_PATH))
    cfg["access_token"] = jwt_token
    cfg["refresh_token"] = refresh_token or ""
    cfg["token_time"] = datetime.now().isoformat()
    cfg["token_expires"] = "5 minutes (approx)"
    json.dump(cfg, open(CONFIG_PATH, "w"), indent=4)
    print("    Saved to config.json")

    # ================================================================
    # STEP 2: Test all endpoints
    # ================================================================
    print("\n[2] Testing API endpoints...")

    tests = [
        ("GET",  "/typeb/user/fundsummary",    "Fund Summary"),
        ("GET",  "/typeb/portfolio/holdings",  "Holdings"),
        ("GET",  "/typeb/orders",              "Orders"),
        ("GET",  "/typeb/trades",              "Trades"),
        ("GET",  "/typeb/position",            "Positions"),
    ]

    for method, path, name in tests:
        status, text = api(method, path, jwt=jwt_token)
        short = path.split("/")[-1]
        if status == 200:
            resp = json.loads(text)
            data = resp.get("data", [])
            if isinstance(data, list):
                print(f"  [OK]  {name}: {len(data)} records")
            elif isinstance(data, dict):
                print(f"  [OK]  {name}: {json.dumps(data)[:100]}")
            else:
                print(f"  [OK]  {name}: {str(data)[:100]}")
        else:
            print(f"  [FAIL] {name}: {status} | {text[:100]}")

    # ================================================================
    # STEP 3: Place a test order (Bank Nifty)
    # ================================================================
    print("\n[3] Bank Nifty instrument search...")
    status, text = api("GET", "/typeb/instruments?exchange=NSEFO&symbol=BAN", jwt=jwt_token)
    if status == 200:
        resp = json.loads(text)
        print(f"    Search results: {json.dumps(resp)[:300]}")
    else:
        print(f"    Search: {status} | {text[:200]}")

    print("\n" + "=" * 60)
    print("  DONE - M-Stock is connected!")
    print("=" * 60)


if __name__ == "__main__":
    main()
