"""
================================================================================
M-STOCK TYPE B - SMS OTP LOGIN
================================================================================
Usage:
  python auth_typeb_sms.py <sms_otp>
  Example: python auth_typeb_sms.py 123456

Step 1: Login (sends SMS OTP) - run without args first
  python auth_typeb_sms.py

Step 2: Verify OTP - run with the 6-digit SMS code
  python auth_typeb_sms.py 123456
================================================================================
"""

import json, os, sys, requests

config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path) as f:
    config = json.load(f)

API_KEY     = config.get('api_key', 'G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y=')
CLIENT_CODE = config.get('client_code', 'MA1116489')
PASSWORD   = config.get('password', 'RAJ123RAJ@r2')
API_URL    = "https://api.mstock.trade"

HEADERS = {"X-Mirae-Version": "1", "Content-Type": "application/json"}


def step1_login():
    """Step 1: Login with credentials - triggers SMS OTP."""
    print("="*60)
    print("  M-STOCK TYPE B - LOGIN (Send SMS OTP)")
    print("="*60)

    payload = {
        "clientCode": CLIENT_CODE,
        "password": PASSWORD,
        "totp": "",  # Will be filled by SMS
        "state": "mstock_trading_bot"
    }

    r = requests.post(
        f"{API_URL}/openapi/typeb/connect/login",
        json=payload,
        headers=HEADERS,
        timeout=30
    )

    print(f"Status: {r.status_code}")
    print(f"Body:   {r.text[:600]}")

    if r.status_code == 200:
        data = r.json()
        if data.get('status') == True:
            resp = data.get('data', {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            print(f"\n[OK] Login step 1 succeeded.")
            print(f"Keys in response: {list(resp.keys())}")
            return resp
        else:
            print(f"Error: {data.get('message', 'Unknown')}")
    elif r.status_code == 400:
        err = r.json()
        print(f"Validation errors: {err.get('errors', {})}")
    return None


def step2_verify(otp_code):
    """Step 2: Verify SMS OTP to get access token."""
    print(f"\n[STEP 2] Verifying OTP: {otp_code[:3]}***")

    payload = {
        "clientCode": CLIENT_CODE,
        "password": PASSWORD,
        "totp": otp_code,
        "state": "mstock_trading_bot"
    }

    r = requests.post(
        f"{API_URL}/openapi/typeb/connect/login",
        json=payload,
        headers=HEADERS,
        timeout=30
    )

    print(f"Status: {r.status_code}")
    print(f"Body:   {r.text[:800]}")

    if r.status_code == 200:
        data = r.json()
        if data.get('status') == True:
            resp = data.get('data', {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}

            jwt = resp.get('jwtToken') or resp.get('accessToken') or resp.get('token') or ''
            refresh = resp.get('refreshToken') or resp.get('refresh_token') or ''

            if jwt:
                print(f"\n[SUCCESS] Access token: {jwt[:30]}...")

                # Save tokens
                config['access_token'] = jwt
                config['refresh_token'] = refresh
                config['totp'] = otp_code
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)

                # Test connection
                test_connection(jwt)
                return jwt
            else:
                print(f"\n[INFO] Response: {json.dumps(resp, indent=2)}")
        else:
            print(f"Error: {data.get('message', 'Unknown')}")
    return None


def step2_session_token(request_token, otp_code, refresh_token=None):
    """Alternative: /session/token endpoint."""
    print(f"\n[STEP 2b] Trying /session/token...")

    payload = {
        "request_token": request_token or "",
        "otp": otp_code,
        "refreshToken": refresh_token or ""
    }

    headers = dict(HEADERS)
    headers["X-PrivateKey"] = API_KEY

    r = requests.post(
        f"{API_URL}/openapi/typeb/session/token",
        json=payload,
        headers=headers,
        timeout=30
    )

    print(f"Status: {r.status_code}")
    print(f"Body:   {r.text[:600]}")

    if r.status_code == 200:
        data = r.json()
        if data.get('status') == True:
            resp = data.get('data', {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            jwt = resp.get('jwtToken') or resp.get('token') or ''
            if jwt:
                config['access_token'] = jwt
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                test_connection(jwt)
                return jwt
    return None


def test_connection(access_token):
    """Test the access token."""
    print("\n[TEST] Testing connection...")

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {access_token}",
        "X-PrivateKey": API_KEY
    }

    r = requests.get(
        f"{API_URL}/openapi/typeb/user/fundsummary",
        headers=headers,
        timeout=30
    )

    print(f"Status: {r.status_code}")
    print(f"Body:   {r.text[:800]}")

    if r.status_code == 200:
        data = r.json()
        for item in data.get('data', []):
            seg = item.get('SEG', 'N/A')
            avail = item.get('AVAILABLE_BALANCE', '0')
            print(f"\n[CONNECTED] Segment: {seg} | Balance: Rs.{avail}")
        return True
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Step 1: Send SMS OTP
        result = step1_login()
        if result:
            print("\n[SMS OTP sent to your registered mobile number]")
            print("Then run: python auth_typeb_sms.py <otp_code>")
    else:
        # Step 2: Verify OTP
        otp = sys.argv[1].strip()
        if len(otp) != 6 or not otp.isdigit():
            print(f"Invalid OTP: {otp} (must be 6 digits)")
            sys.exit(1)

        # First try login with OTP
        jwt = step2_verify(otp)

        if not jwt:
            # Try session/token endpoint
            jwt = step2_session_token("", otp, "")

        if jwt:
            print("\n[M-STOCK CONNECTED - TYPE B SMS OTP SUCCESSFUL]")
        else:
            print("\n[FAILED] OTP verification unsuccessful.")
            print("         The OTP may have expired. Run Step 1 again.")
