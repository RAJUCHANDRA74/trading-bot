"""
Try generating TOTP using the API_SECRET as raw bytes (not base32).
"""

import json, base64, pyotp, requests

config_path = "C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/data/config.json"
with open(config_path) as f:
    config = json.load(f)

CLIENT_CODE = config['client_code']
API_SECRET  = config['api_secret']
PASSWORD    = config.get('password', 'RAJ123RAJ@r2')
API_URL     = "https://api.mstock.trade"

HEADERS = {"X-Mirae-Version": "1", "Content-Type": "application/json"}

# Method: decode base64, use raw bytes as TOTP seed
decoded = base64.b64decode(API_SECRET)
print(f"Decoded bytes: {decoded.hex()}")
print(f"Length: {len(decoded)} bytes")

try:
    # Try with raw bytes directly (pyotp accepts bytes)
    totp = pyotp.TOTP(decoded)
    code = totp.now()
    print(f"\nGenerated TOTP (raw bytes): {code}")

    # Try login with this code
    print(f"\n[TEST] Logging in with generated TOTP: {code}")
    r = requests.post(
        f"{API_URL}/openapi/typeb/connect/login",
        json={
            "clientCode": CLIENT_CODE,
            "password": PASSWORD,
            "totp": code,
            "state": "minimax_bot_v1"
        },
        headers=HEADERS,
        timeout=30
    )
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text[:400]}")

    if r.status_code == 200:
        data = r.json()
        if data.get('status') == True:
            print("\n[SUCCESS] Login worked with generated TOTP!")
            resp = data.get('data', {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            print(f"Keys: {list(resp.keys())}")
            print(f"Response: {json.dumps(resp, indent=2)[:600]}")

            # Save for next step
            with open("C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/data/login_response.json", 'w') as f:
                json.dump(resp, f, indent=2)
            print("\n[SAVED] Response saved to data/login_response.json")
        else:
            print(f"Login returned status=False: {data}")
    else:
        print(f"\n[EXPECTED] Login failed — this tells us if TOTP format is right or wrong")
        print(f"Error: {r.text[:200]}")

except Exception as e:
    print(f"Error: {e}")
