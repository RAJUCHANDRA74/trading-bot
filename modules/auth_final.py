"""
================================================================================
M-STOCK API - AUTHENTICATION (accepts TOTP via command line)
================================================================================
Usage:
  python modules/auth_final.py <totp_code>

Example:
  python modules/auth_final.py 123456
================================================================================
"""

import json, os, sys, requests, base64, time

config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path) as f:
    config = json.load(f)

CLIENT_CODE = config['client_code']
API_SECRET  = config['api_secret']
PASSWORD    = config.get('password', 'RAJ123RAJ@r2')
API_URL     = "https://api.mstock.trade"

HEADERS = {"X-Mirae-Version": "1", "Content-Type": "application/json"}


def step1_login(totp_code):
    """POST /openapi/typeb/connect/login"""
    r = requests.post(
        f"{API_URL}/openapi/typeb/connect/login",
        json={
            "clientCode": CLIENT_CODE,
            "password": PASSWORD,
            "totp": totp_code,
            "state": "minimax_trading_bot_v1"
        },
        headers=HEADERS,
        timeout=30
    )
    print(f"[STEP1] Status: {r.status_code} | Body: {r.text[:400]}")
    if r.status_code == 200:
        data = r.json()
        if data.get('status') == True:
            resp = data.get('data', {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            return resp
    return None


def step2_verify_totp(refresh_token, totp_code):
    """POST /openapi/typeb/session/verifytotp"""
    headers = dict(HEADERS)
    headers["X-PrivateKey"] = CLIENT_CODE

    r = requests.post(
        f"{API_URL}/openapi/typeb/session/verifytotp",
        json={
            "totp": totp_code,
            "refreshToken": refresh_token
        },
        headers=headers,
        timeout=30
    )
    print(f"[STEP2] Status: {r.status_code} | Body: {r.text[:500]}")
    if r.status_code == 200:
        data = r.json()
        if data.get('status') == True:
            resp = data.get('data', {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            return resp
    return None


def step2_session_token(request_token, otp_code, refresh_token):
    """POST /openapi/typeb/session/token"""
    headers = dict(HEADERS)
    headers["X-PrivateKey"] = CLIENT_CODE

    r = requests.post(
        f"{API_URL}/openapi/typeb/session/token",
        json={
            "request_token": request_token or "",
            "otp": otp_code,
            "refreshToken": refresh_token
        },
        headers=headers,
        timeout=30
    )
    print(f"[SESSION] Status: {r.status_code} | Body: {r.text[:500]}")
    if r.status_code == 200:
        data = r.json()
        if data.get('status') == True:
            resp = data.get('data', {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            return resp
    return None


def test_connection(access_token):
    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {access_token}",
        "X-PrivateKey": CLIENT_CODE
    }
    r = requests.get(f"{API_URL}/openapi/typeb/user/fundsummary", headers=headers, timeout=30)
    print(f"[TEST] Status: {r.status_code} | Body: {r.text[:600]}")
    if r.status_code == 200:
        data = r.json()
        for item in data.get('data', []):
            print(f"    Segment: {item.get('SEG')} | Balance: Rs.{item.get('AVAILABLE_BALANCE')}")
        return True
    return False


def save_tokens(access_token, refresh_token=None):
    config['access_token'] = access_token
    if refresh_token:
        config['refresh_token'] = refresh_token
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)
    print("[SAVED] Tokens saved.")


if __name__ == "__main__":
    print("="*60)
    print("  M-STOCK - AUTHENTICATION")
    print("="*60)

    if len(sys.argv) < 2:
        print("\n[USAGE] python auth_final.py <totp_code>")
        print("        Get the 6-digit code from your Google Authenticator app")
        print("        (M-Stock or Mirae Asset), then run this command QUICKLY")
        print("        because the code changes every 30 seconds.")
        sys.exit(1)

    totp1 = sys.argv[1].strip()

    if len(totp1) != 6 or not totp1.isdigit():
        print(f"[ERROR] TOTP must be 6 digits. Got: '{totp1}'")
        sys.exit(1)

    print(f"\n[INFO] Using TOTP: {totp1[:2]}**{totp1[-1]}")

    # Step 1: Login
    print("\n[STEP 1] Logging in with TOTP...")
    login_result = step1_login(totp1)

    if not login_result:
        print("[FAILED] Login failed. Check your TOTP and password.")
        sys.exit(1)

    refresh_token = (
        login_result.get('refreshToken') or
        login_result.get('refresh_token') or
        login_result.get('token')
    )
    request_token = login_result.get('request_token', '')

    print(f"\n[INFO] Got login response. refreshToken: {str(refresh_token)[:15] if refresh_token else 'NONE'}...")
    print(f"[INFO] Response keys: {list(login_result.keys())}")

    if not refresh_token:
        print(f"\n[ERROR] No refreshToken in response!")
        print(f"Full response: {json.dumps(login_result, indent=2)}")
        sys.exit(1)

    # Need second TOTP for step 2
    if len(sys.argv) >= 3:
        totp2 = sys.argv[2].strip()
    else:
        print("\n[PROMPT] Enter SECOND TOTP code (for Step 2 - verifytotp):")
        print("  Wait for the code to CHANGE in Google Authenticator, then enter it.")
        totp2 = sys.argv[1].strip() if len(sys.argv) < 3 else ""

    if len(totp2) != 6 or not totp2.isdigit():
        print(f"[WARN] Second TOTP invalid: '{totp2}' — trying same code...")
        totp2 = totp1  # Will likely fail but we can see the error

    # Step 2a: verifytotp
    print(f"\n[STEP 2] Calling verifytotp with TOTP: {totp2[:2]}**...")
    verify_result = step2_verify_totp(refresh_token, totp2)

    access_token = None

    if verify_result:
        access_token = (
            verify_result.get('jwtToken') or
            verify_result.get('accessToken') or
            verify_result.get('token')
        )

    # Step 2b: session/token (fallback)
    if not access_token:
        print("\n[FALLBACK] Trying session/token endpoint...")
        session_result = step2_session_token(request_token, totp2, refresh_token)
        if session_result:
            access_token = (
                session_result.get('jwtToken') or
                session_result.get('accessToken') or
                session_result.get('token')
            )

    if access_token:
        print(f"\n[SUCCESS!] Access token: {access_token[:30]}...")
        save_tokens(access_token, refresh_token)
        test_connection(access_token)
    else:
        print("\n[FAILED] Could not get access token.")
        print("\n[NOTE] Both verifytotp and session/token failed.")
        print("        M-Stock requires 2 TOTP codes (one for login, one for verify).")
        print("        Try: python auth_final.py <totp1> <totp2>")
        print("        where totp2 is the NEXT code that appears in Google Auth.")
