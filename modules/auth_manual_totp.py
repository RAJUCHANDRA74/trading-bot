"""
================================================================================
M-STOCK - LOGIN WITH MANUAL TOTP
================================================================================
Run this script each time you want to connect to M-Stock.
It will ask for your 6-digit TOTP code from Google Authenticator.

Usage:
  python modules/auth_manual_totp.py

The script saves your access token to config.json so you don't need
to re-authenticate until midnight (tokens expire at end of day).
================================================================================
"""

import json, os, sys, requests
from SmartApi import SmartConnect

config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path) as f:
    config = json.load(f)

CLIENT_CODE = config.get('client_code', 'MA1116489')
API_KEY     = config.get('api_key', 'G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y=')
PASSWORD    = config.get('password', 'RAJ123RAJ@r2')


def get_totp():
    """Ask user for TOTP code."""
    print("\n" + "="*60)
    print("  M-STOCK TOTP REQUIRED")
    print("="*60)
    print("  Open Google Authenticator on your phone.")
    print("  Find 'M-Stock' or 'Mirae Asset'.")
    print("  Enter the 6-digit code shown.")
    print("  (Code changes every 30 seconds)")
    print("="*60)
    for attempt in range(3):
        code = input(f"\n  Enter TOTP code (attempt {attempt+1}/3): ").strip()
        if len(code) == 6 and code.isdigit():
            return code
        print("  Invalid. Please enter exactly 6 digits.")
    return None


def login(totp):
    """Login to M-Stock using SmartAPI with TOTP."""
    try:
        obj = SmartConnect(api_key=API_KEY)
        data = obj.generateSession(CLIENT_CODE, PASSWORD, totp)

        if data and data.get('status'):
            resp = data['data']
            jwt = resp.get('jwtToken', '')
            feed = resp.get('feedToken', '')
            refresh = resp.get('refreshToken', '')

            print(f"\n  Logged in as: {resp.get('name', 'N/A')}")
            print(f"  Client: {resp.get('clientcode', 'N/A')}")

            # Save tokens
            config['access_token'] = jwt
            config['feed_token'] = feed
            config['refresh_token'] = refresh
            config['smartapi_obj'] = True  # flag that SmartAPI is configured
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)

            return obj
        else:
            print(f"\n  Login failed: {data.get('message', 'Unknown error')}")
            return None

    except Exception as e:
        print(f"\n  Error: {e}")
        return None


def test_connection(obj):
    """Test the connection."""
    try:
        profile = obj.getProfile()
        print(f"\n  Profile OK: {profile.get('data', {}).get('name', 'N/A')}")

        margins = obj.getMargins()
        for seg, data in margins.items():
            if isinstance(data, dict):
                avail = data.get('available', {})
                cash = avail.get('cash', 0)
                print(f"  {seg.upper()}: Available Cash = Rs.{cash:,.0f}")
        return True
    except Exception as e:
        print(f"  Connection test failed: {e}")
        return False


if __name__ == "__main__":
    print("="*60)
    print("  M-STOCK - CONNECT")
    print("="*60)
    print(f"  Client: {CLIENT_CODE}")

    totp = get_totp()
    if not totp:
        print("\n  No TOTP provided. Exiting.")
        sys.exit(1)

    obj = login(totp)
    if obj:
        print("\n[SUCCESS] M-Stock connected!")
        test_connection(obj)
        print("\n  Token saved to config.json.")
        print("  You can now run your trading bot.")
    else:
        print("\n[FAILED] Login unsuccessful.")
        print("  Possible causes:")
        print("  - Wrong TOTP code")
        print("  - TOTP code expired (30-second window)")
        print("  - Wrong password in config.json")
