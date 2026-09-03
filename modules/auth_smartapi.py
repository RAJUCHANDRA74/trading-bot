"""
================================================================================
M-STOCK via SmartAPI - AUTHENTICATION
================================================================================
Uses smartapi-python library with MPIN (not TOTP).
"""

import json, os, sys
from SmartApi import SmartConnect

# Load config
config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path) as f:
    config = json.load(f)

CLIENT_CODE = config.get('client_code', 'MA1116489')
API_KEY    = config.get('api_key', 'fMxt3m1A0XdOr15zCj7Zc32BEiEqbjUqf4ODOBtzNMo=')
PASSWORD   = config.get('password', 'RAJ123RAJ@r2')
API_URL    = "https://api.mstock.trade"

# Try both potential MPINs
MPINS = ['1980', '301080', PASSWORD]


def try_login(mpin):
    """Try to authenticate with SmartConnect using mpin."""
    print(f"\n[TRY] MPIN: {'*' * len(mpin)} ({mpin})")

    try:
        obj = SmartConnect(api_key=API_KEY)

        # Login with client code + password + mpin
        data = obj.generateSession(CLIENT_CODE, mpin)

        print(f"    Response type: {type(data)}")
        print(f"    Response: {str(data)[:500]}")

        if data and data.get('status'):
            resp = data.get('data', {})
            print(f"\n    [SUCCESS] Logged in!")
            print(f"    User: {resp.get('name', 'N/A')}")
            print(f"    Email: {resp.get('email', 'N/A')}")
            print(f"    Auth Token: {str(resp.get('jwtToken', ''))[:30]}...")

            # Save tokens
            config['access_token'] = resp.get('jwtToken', '')
            config['refresh_token'] = resp.get('refreshToken', '')
            config['feed_token'] = resp.get('feedToken', '')
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)

            # Test: get profile
            profile = obj.getProfile()
            print(f"\n    Profile: {json.dumps(profile, indent=2)[:400]}")

            # Test: get margins
            margins = obj.getMargins()
            print(f"\n    Margins: {json.dumps(margins, indent=2)[:600]}")

            return obj

        else:
            msg = data.get('message', 'Unknown error') if data else 'No response'
            print(f"    [FAILED] {msg}")
            return None

    except Exception as e:
        print(f"    [ERROR] {e}")
        return None


if __name__ == "__main__":
    print("="*60)
    print("  M-STOCK via SmartAPI - LOGIN")
    print("="*60)
    print(f"  Client Code: {CLIENT_CODE}")
    print(f"  API Key:    {API_KEY[:20]}...")
    print(f"  Testing {len(MPINS)} MPIN options...")

    for mpin in MPINS:
        print("\n" + "="*50)
        result = try_login(mpin)
        if result:
            print("\n[LOGIN SUCCESSFUL]")
            break
        else:
            print(f"[FAILED] Moving to next option...")
