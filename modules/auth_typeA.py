"""
================================================================================
M-STOCK TYPE A API - SMS OTP AUTHENTICATION
================================================================================
Type A: Uses SMS OTP instead of TOTP
Flow:
  Step 1: POST /openapi/typea/connect/login  → sends OTP to phone
  Step 2: POST /openapi/typea/session/token → exchanges OTP for JWT access token
================================================================================
"""

import json, os, sys, hashlib, hmac, requests, time

config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path) as f:
    config = json.load(f)

API_KEY    = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="  # NEW key
PASSWORD   = config.get('password', 'RAJ123RAJ@r2')
CLIENT_CODE = config.get('client_code', 'MA1116489')
API_URL    = "https://api.mstock.trade"

HEADERS = {"X-Mirae-Version": "1", "Content-Type": "application/json"}


def generate_checksum(api_key, request_token, api_secret):
    """Generate checksum for session token request."""
    message = f"{api_key}:{request_token}"
    checksum = hmac.new(
        api_secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return checksum


def step1_send_otp():
    """Step 1: Login to send OTP to registered mobile."""
    print("\n[STEP 1] Sending OTP to your registered mobile...")

    # Update config with new API key
    config['api_key'] = API_KEY
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)

    payload = {
        "api_key": API_KEY,
        "password": PASSWORD
    }

    r = requests.post(
        f"{API_URL}/openapi/typea/connect/login",
        json=payload,
        headers=HEADERS,
        timeout=30
    )

    print(f"    Status: {r.status_code}")
    print(f"    Body:   {r.text[:500]}")

    if r.status_code == 200:
        data = r.json()
        if data.get('status') == True:
            resp = data.get('data', {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            print(f"\n[SUCCESS] OTP sent to your mobile!")
            return resp
        else:
            print(f"[ERROR] {data.get('message', 'Unknown')}")
    return None


def step2_exchange_otp(otp_code):
    """Step 2: Exchange OTP for access token."""
    print(f"\n[STEP 2] Exchanging OTP for access token...")
    print(f"    Note: OTP = {otp_code[:3]}*** (from SMS)")

    # Use API_KEY as the api_secret for checksum (Type A format)
    checksum = generate_checksum(API_KEY, otp_code, API_KEY)

    payload = {
        "api_key": API_KEY,
        "request_token": otp_code,
        "checksum": checksum
    }

    r = requests.post(
        f"{API_URL}/openapi/typea/session/token",
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

            jwt = resp.get('jwtToken') or resp.get('token') or ''
            if jwt:
                print(f"\n[SUCCESS] Access token: {jwt[:30]}...")

                # Save tokens
                config['access_token'] = jwt
                config['refresh_token'] = resp.get('refreshToken', '')
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)

                return jwt
        else:
            print(f"[ERROR] {data.get('message', 'Unknown')}")
    return None


def test_connection(access_token):
    """Test authenticated API call."""
    print("\n[TEST] Testing connection...")

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {access_token}",
        "X-PrivateKey": API_KEY
    }

    r = requests.get(
        f"{API_URL}/openapi/typea/user/fundsummary",
        headers=headers,
        timeout=30
    )

    print(f"    Status: {r.status_code}")
    print(f"    Body:   {r.text[:800]}")

    if r.status_code == 200:
        data = r.json()
        for item in data.get('data', []):
            seg = item.get('SEG', 'N/A')
            avail = item.get('AVAILABLE_BALANCE', '0')
            print(f"\n    [CONNECTED] Segment: {seg} | Balance: Rs.{avail}")
        return True
    return False


if __name__ == "__main__":
    print("="*60)
    print("  M-STOCK TYPE A - SMS OTP AUTHENTICATION")
    print("="*60)

    # Step 1: Send OTP
    result = step1_send_otp()

    if not result:
        print("\n[FAILED] Could not send OTP. Check:")
        print("  1. Is the new API key correct?")
        print("  2. Is the password correct?")
        sys.exit(1)

    # Step 2: Get OTP from user
    print("\n" + "="*60)
    print("  ENTER OTP")
    print("="*60)
    print("  An OTP has been sent to your registered mobile number.")
    print("  Enter the 6-digit code below.")
    print("="*60)

    if len(sys.argv) >= 2:
        otp = sys.argv[1].strip()
    else:
        otp = input("\n  Enter 6-digit OTP from SMS: ").strip()

    if len(otp) != 6 or not otp.isdigit():
        print(f"[ERROR] Invalid OTP: {otp}")
        sys.exit(1)

    # Exchange OTP for token
    access_token = step2_exchange_otp(otp)

    if access_token:
        test_connection(access_token)
        print("\n[LOGIN SUCCESSFUL - M-STOCK TYPE A CONNECTED!]")
    else:
        print("\n[FAILED] OTP exchange failed. The OTP may have expired.")
        print("         Run the script again: python auth_typeA.py")
