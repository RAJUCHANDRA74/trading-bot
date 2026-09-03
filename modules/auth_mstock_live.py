"""
================================================================================
M-STOCK - LIVE LOGIN WITH TOTP SECRET + SMS OTP
================================================================================
Uses the TOTP secret to auto-generate Google Authenticator codes.
Steps:
  1. Generate TOTP from secret
  2. Login with TOTP → sends SMS OTP to your mobile
  3. Enter SMS OTP → exchange for access token
================================================================================
"""

import requests, json, sys, os, pyotp

API_URL     = "https://api.mstock.trade"
CLIENT_CODE = "MA1116489"
PASSWORD    = "RAJ123RAJ@r2"
API_KEY     = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="
TOTP_SECRET = "YV6B24K7VV4VTDWJWX5CAYCDIUQ4GKVG"   # Your Google Auth secret
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")


def generate_totp():
    """Generate current TOTP code from secret."""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.now()


def step1_login_totp():
    """Login with TOTP → sends SMS OTP."""
    code = generate_totp()
    print(f"  TOTP generated: {code[:3]}****")

    r = requests.post(
        f"{API_URL}/openapi/typeb/connect/login",
        json={"clientCode": CLIENT_CODE, "password": PASSWORD, "totp": code, "state": "bot"},
        headers={"X-Mirae-Version": "1", "Content-Type": "application/json"},
        timeout=30
    )
    data = r.json()
    if data.get('status'):
        refresh = data['data']['refreshToken']
        print("  Logged in via TOTP.")
        print("  SMS OTP sent to your registered mobile!")
        return refresh
    print(f"  Login failed: {data}")
    return None


def step2_exchange_sms(refresh, sms_otp):
    """Exchange SMS OTP for access token."""
    r = requests.post(
        f"{API_URL}/openapi/typeb/session/token",
        json={"refreshToken": refresh, "otp": sms_otp},
        headers={"X-Mirae-Version": "1", "Content-Type": "application/json", "X-PrivateKey": API_KEY},
        timeout=30
    )
    return r.json()


def test_connection(jwt):
    """Test the access token."""
    r = requests.get(
        f"{API_URL}/openapi/typeb/user/fundsummary",
        headers={"X-Mirae-Version": "1", "Authorization": f"Bearer {jwt}", "X-PrivateKey": API_KEY},
        timeout=30
    )
    return r.json()


def main():
    print("="*60)
    print("  M-STOCK - LIVE LOGIN")
    print("="*60)

    # Step 1: Login with TOTP
    print("\n[1] Logging in with TOTP (auto-generated)...")
    refresh = step1_login_totp()
    if not refresh:
        sys.exit(1)

    # Save refresh token
    cfg = json.load(open(CONFIG_PATH))
    cfg['refresh_token'] = refresh
    json.dump(cfg, open(CONFIG_PATH, 'w'), indent=4)

    # Step 2: Ask for SMS OTP
    print("\n[2] Enter the SMS OTP sent to your mobile.")
    print("    (Act fast — expires in ~30 seconds)\n")

    for attempt in range(5):
        try:
            sms_code = input(f"    Enter SMS OTP (attempt {attempt+1}/5): ").strip()
        except EOFError:
            print("\nRun from terminal.")
            sys.exit(1)

        if len(sms_code) != 6 or not sms_code.isdigit():
            print("    Invalid. Enter exactly 6 digits.")
            continue

        print(f"    Exchanging SMS OTP: {sms_code[:2]}**** ...")
        result = step2_exchange_sms(refresh, sms_code)

        if result.get('status'):
            jwt = result['data'].get('jwtToken') or result['data'].get('token') or ''
            if jwt:
                print(f"\n[SUCCESS!] Token: {jwt[:40]}...")

                cfg['access_token'] = jwt
                json.dump(cfg, open(CONFIG_PATH, 'w'), indent=4)

                print("\n[3] Testing connection...")
                test = test_connection(jwt)
                print(f"    Fund summary: {json.dumps(test)[:400]}")

                print("\n[M-STOCK FULLY CONNECTED!]")
                return

        msg = result.get('message', 'Unknown')
        print(f"    {msg}")

        if 'expired' in msg.lower():
            print("    SMS OTP expired. Resending...")
            # Resend SMS by logging in again
            refresh = step1_login_totp()
            if not refresh:
                sys.exit(1)
            cfg['refresh_token'] = refresh
            json.dump(cfg, open(CONFIG_PATH, 'w'), indent=4)

    print("\nToo many attempts. Run again.")


if __name__ == "__main__":
    main()
