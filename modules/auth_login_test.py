"""
================================================================================
M-STOCK API - STEP 1: LOGIN + STEP 2: GET TOKENS
================================================================================
Based on diagnostic results:
- /openapi/typeb/connect/login  → needs: clientCode, password, totp, state
- /openapi/typeb/session/token → needs: request_token, otp, refreshToken
- /openapi/typeb/session/verifytotp → needs: totp, refreshToken
================================================================================
"""

import json, os, sys, requests, hashlib, hmac, base64, time

config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path) as f:
    config = json.load(f)

CLIENT_CODE = config['client_code']
API_SECRET  = config['api_secret']
PASSWORD    = config.get('password', 'RAJ123RAJ@r2')
API_URL     = "https://api.mstock.trade"

HEADERS = {
    "X-Mirae-Version": "1",
    "Content-Type": "application/json"
}


def generate_totp(secret_b64):
    """Try to generate TOTP from base64-encoded API secret."""
    try:
        import pyotp
        # The API secret is base64 — decode it to bytes
        raw = base64.b32decode(secret_b64.upper(), casefold=True)
        totp = pyotp.TOTP(raw)
        code = totp.now()
        print(f"    [TOTP] Generated: {code}")
        return code
    except Exception as e:
        print(f"    [TOTP] Generation failed: {e}")
        # Try as raw secret
        try:
            totp = pyotp.TOTP(secret_b64)
            code = totp.now()
            print(f"    [TOTP] Generated (raw): {code}")
            return code
        except:
            print(f"    [TOTP] All attempts failed")
            return None


def step1_login(totp_code):
    """Call /openapi/typeb/connect/login with totp + state."""
    print("\n[STEP 1] Calling login endpoint...")

    payload = {
        "clientCode": CLIENT_CODE,
        "password": PASSWORD,
        "totp": totp_code,
        "state": "mstock_api_flow_001"
    }

    print(f"    Payload: clientCode={CLIENT_CODE}, totp={totp_code[:3]}***, state=***")

    try:
        r = requests.post(
            f"{API_URL}/openapi/typeb/connect/login",
            json=payload,
            headers=HEADERS,
            timeout=30
        )
        print(f"    Status: {r.status_code}")
        print(f"    Body:   {r.text[:600]}")

        if r.status_code == 200:
            data = r.json()
            if data.get('status') == True:
                resp = data.get('data', {})
                if isinstance(resp, list):
                    resp = resp[0] if resp else {}
                print(f"\n[SUCCESS] Login response keys: {list(resp.keys())}")
                return resp
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def step2_session_tokens(request_token_from_login, totp_code, refresh_token=None):
    """Call /openapi/typeb/session/token to get access token."""
    print("\n[STEP 2] Calling session/token endpoint...")

    payload = {
        "request_token": request_token_from_login or "",
        "otp": totp_code,
        "refreshToken": refresh_token or ""
    }

    headers = dict(HEADERS)
    headers["X-PrivateKey"] = CLIENT_CODE

    try:
        r = requests.post(
            f"{API_URL}/openapi/typeb/session/token",
            json=payload,
            headers=headers,
            timeout=30
        )
        print(f"    Status: {r.status_code}")
        print(f"    Body:   {r.text[:800]}")

        if r.status_code == 200:
            data = r.json()
            if data.get('status') == True:
                resp = data.get('data', {})
                if isinstance(resp, list):
                    resp = resp[0] if resp else {}
                return resp
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def step2_verify_totp(refresh_token, totp_code):
    """Call /openapi/typeb/session/verifytotp to get access token."""
    print("\n[STEP 2] Calling verifytotp endpoint...")

    payload = {
        "totp": totp_code,
        "refreshToken": refresh_token
    }

    headers = dict(HEADERS)
    headers["X-PrivateKey"] = CLIENT_CODE

    try:
        r = requests.post(
            f"{API_URL}/openapi/typeb/session/verifytotp",
            json=payload,
            headers=headers,
            timeout=30
        )
        print(f"    Status: {r.status_code}")
        print(f"    Body:   {r.text[:800]}")

        if r.status_code == 200:
            data = r.json()
            if data.get('status') == True:
                resp = data.get('data', {})
                if isinstance(resp, list):
                    resp = resp[0] if resp else {}
                return resp
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def test_authenticated_call(access_token):
    """Test an authenticated API call."""
    print("\n[TEST] Testing authenticated call (fund summary)...")

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {access_token}",
        "X-PrivateKey": CLIENT_CODE
    }

    try:
        r = requests.get(
            f"{API_URL}/openapi/typeb/user/fundsummary",
            headers=headers,
            timeout=30
        )
        print(f"    Status: {r.status_code}")
        print(f"    Body:   {r.text[:1000]}")

        if r.status_code == 200:
            data = r.json()
            funds = data.get('data', [])
            if isinstance(funds, list):
                for item in funds:
                    seg = item.get('SEG', 'N/A')
                    avail = item.get('AVAILABLE_BALANCE', '0')
                    print(f"\n    [SUCCESS] Segment: {seg} | Available Balance: Rs.{avail}")
            return True
        return False
    except Exception as e:
        print(f"    Error: {e}")
        return False


if __name__ == "__main__":
    print("="*60)
    print("  M-STOCK - TWO-STEP AUTHENTICATION")
    print("="*60)

    # Generate TOTP
    totp_code = generate_totp(API_SECRET)

    if not totp_code:
        print("\n[ERROR] Cannot generate TOTP. The API_SECRET may not be a valid TOTP seed.")
        print("        You may need the actual TOTP secret from M-Stock website.")
        print("        Go to: https://www.mstock.com -> Settings -> API -> Regenerate")
        sys.exit(1)

    # Step 1: Login
    login_result = step1_login(totp_code)

    access_token = None

    if login_result:
        print(f"\n[INFO] Login response: {json.dumps(login_result, indent=2)[:600]}")

        # Try to extract request_token from login response
        request_token = login_result.get('request_token') or login_result.get('sessionToken') or login_result.get('token')

        # Try Step 2a: session/token
        session_result = step2_session_tokens(request_token, totp_code,
            login_result.get('refreshToken') or login_result.get('refresh_token'))

        if session_result:
            jwt = session_result.get('jwtToken') or session_result.get('accessToken') or session_result.get('token')
            if jwt:
                print(f"\n[SUCCESS] Access token: {jwt[:30]}...")

                # Save
                config['access_token'] = jwt
                config['refresh_token'] = session_result.get('refreshToken') or login_result.get('refreshToken')
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)

                # Test
                test_authenticated_call(jwt)
            else:
                print(f"\n[INFO] Session response: {json.dumps(session_result, indent=2)[:600]}")
        else:
            # Try Step 2b: verifytotp
            refresh = login_result.get('refreshToken') or login_result.get('refresh_token')
            if refresh:
                verify_result = step2_verify_totp(refresh, totp_code)
                if verify_result:
                    jwt = verify_result.get('jwtToken') or verify_result.get('accessToken')
                    if jwt:
                        print(f"\n[SUCCESS] Access token: {jwt[:30]}...")
                        config['access_token'] = jwt
                        config['refresh_token'] = refresh
                        with open(config_path, 'w') as f:
                            json.dump(config, f, indent=4)
                        test_authenticated_call(jwt)
    else:
        print("\n[NOTE] Login failed. This likely means:")
        print("        1. The TOTP code is wrong (API_SECRET is not a valid TOTP seed)")
        print("        2. You need to regenerate your API key on M-Stock to get the TOTP secret")
        print("")
        print("        ACTION REQUIRED:")
        print("        1. Log into https://www.mstock.com")
        print("        2. Go to Profile/Settings -> API Management")
        print("        3. Look for 'TOTP Secret' or 'Regenerate API Key'")
        print("        4. Share the TOTP Secret with me (it's a 32-char base32 string)")
