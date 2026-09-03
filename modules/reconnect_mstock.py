"""Re-authenticate with M-Stock - with retry loop."""
from tradingapi_b.mconnect import MConnectB
import pyotp, json, time
from datetime import datetime

API_KEY = "06SomqZj4ZsvaWc0se3gc0Y1OFbpAIj6CS8W8tQTI/M="
TOTP_SECRET = "YV6B24K7VV4VTDWJWX5CAYCDIUQ4GKVG"
MAX_RETRIES = 10

print("Re-connecting to M-Stock...")

for attempt in range(1, MAX_RETRIES + 1):
    try:
        m = MConnectB()
        m.set_api_key(API_KEY)

        lr = m.login("MA1116489", "RAJ123RAJ@r2")
        rt = lr.json()["data"]["refreshToken"]
        totp = pyotp.TOTP(TOTP_SECRET).now()
        vr = m.verify_totp(API_KEY, rt, totp)

        if vr.json().get("status"):
            print(f"Connected! (attempt {attempt}) Time: {datetime.now().strftime('%H:%M:%S')}")

            # Test
            fs = m.get_fund_summary().json()
            d = fs.get("data", [{}])[0]
            balance = d.get("AVAILABLE_BALANCE", "N/A")
            print(f"Balance: Rs.{balance}")

            # Save token
            cfg = json.load(open("data/config.json"))
            cfg["access_token"] = m.access_token
            cfg["token_time"] = datetime.now().isoformat()
            json.dump(cfg, open("data/config.json", "w"), indent=4)
            print("Token saved.")
            break
        else:
            print(f"Attempt {attempt}: Auth failed, retrying...")
            time.sleep(3)

    except Exception as e:
        print(f"Attempt {attempt}: {type(e).__name__} - retrying in 5s...")
        time.sleep(5)
