"""M-Stock OTP login - simple version."""
import requests, json, sys, os, time

API_KEY = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="
CONFIG = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")

cfg = json.load(open(CONFIG))
refresh = cfg.get('refresh_token', '')

if not refresh:
    print("No refresh token. Run auth_mstock_live.py first to get a refresh token.")
    sys.exit(1)

print("Refresh token found. Requesting new OTP...")
r = requests.post(
    'https://api.mstock.trade/openapi/typeb/session/token',
    json={"refreshToken": refresh, "otp": ""},
    headers={'X-Mirae-Version': '1', 'Content-Type': 'application/json', 'X-PrivateKey': API_KEY},
    timeout=30
)
print(f"Status: {r.status_code} | {r.text[:300]}")

if r.status_code == 200:
    data = r.json()
    if data.get('status'):
        print(f"\n[OK] OTP sent to your phone!")
        code = input("Enter 6-digit OTP: ").strip()
        if len(code) == 6 and code.isdigit():
            r2 = requests.post(
                'https://api.mstock.trade/openapi/typeb/session/token',
                json={"refreshToken": refresh, "otp": code},
                headers={'X-Mirae-Version': '1', 'Content-Type': 'application/json', 'X-PrivateKey': API_KEY},
                timeout=30
            )
            data2 = r2.json()
            if data2.get('status'):
                jwt = data2['data'].get('jwtToken') or data2['data'].get('token') or ''
                cfg['access_token'] = jwt
                json.dump(cfg, open(CONFIG, 'w'), indent=4)
                print(f"SAVED! Token: {jwt[:30]}...")
                print("\nM-STOCK CONNECTED!")
            else:
                print(f"Failed: {data2.get('message')}")
        else:
            print("Invalid OTP")
    else:
        print(f"Error: {data.get('message')}")
else:
    print(f"Need fresh refresh token. Run auth_mstock_live.py first.")
