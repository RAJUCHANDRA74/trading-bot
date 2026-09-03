"""
===================================================================
M-STOCK - OAuth Token Capture (Simple Version)
===================================================================
This opens the M-Stock login page in your default browser.
You complete the login (SMS OTP arrives immediately on your phone).
The redirect is captured and tokens are saved.

1. Run this script
2. Your browser opens to M-Stock login
3. Log in with: Client Code = MA1116489, Password = RAJ123RAJ@r2
4. Enter SMS OTP from your phone
5. Done! Tokens are saved automatically.
===================================================================
"""

import json, os, sys, webbrowser, time, uuid, threading
from flask import Flask, request

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
API_KEY = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="
PORT = 5555

app = Flask(__name__)
_captured = {"done": False, "data": None}


@app.route("/")
def callback():
    args = dict(request.args)
    url = request.url
    print(f"\n[CAPTURED] Redirect URL: {url[:200]}")
    print(f"[CAPTURED] Args: {list(args.keys())}")

    _captured["data"] = {"url": url, "args": args, "full_url": url}
    _captured["done"] = True

    # Try to extract tokens
    for key in ["access_token", "token", "jwtToken", "Auth", "auth"]:
        if key in args:
            print(f"[TOKEN] Found '{key}': {str(args[key])[:40]}...")

    return """
    <html><body style="font-family:Arial; text-align:center; padding:60px; background:#e8f5e9;">
    <div style="background:white; border-radius:12px; padding:40px; max-width:500px; margin:0 auto;">
        <h2 style="color:#2e7d32;">Connected!</h2>
        <p>Your trading bot is now connected to M-Stock.</p>
        <p style="color:#888; font-size:14px;">Close this window and return to the terminal.</p>
    </div>
    </body></html>
    """


@app.route("/health")
def health():
    return "OK"


def run_server():
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def save_tokens(data):
    if not data:
        return
    args = data.get("args", {})
    url = data.get("url", "")

    access = (args.get("access_token") or args.get("token")
              or args.get("jwtToken") or args.get("Auth") or args.get("auth"))
    refresh = args.get("refresh_token") or args.get("refreshToken")
    feed = args.get("feedToken") or args.get("feed_token")

    # Fallback: try to find token in URL fragments
    if not access and "#" in url:
        fragment = url.split("#")[1]
        for part in fragment.split("&"):
            if "token=" in part:
                access = part.split("token=")[1].split("&")[0]

    print(f"\n[SAVE] access_token: {str(access)[:30] if access else 'NOT FOUND'}...")
    print(f"[SAVE] refresh_token: {str(refresh)[:30] if refresh else 'NOT FOUND'}...")

    if access:
        cfg = json.load(open(CONFIG_PATH))
        cfg["access_token"] = access
        if refresh:
            cfg["refresh_token"] = refresh
        if feed:
            cfg["feed_token"] = feed
        json.dump(cfg, open(CONFIG_PATH, "w"), indent=4)
        print("[SAVE] Saved to config.json")

        # Decode token to show expiry
        try:
            import base64, time as t
            parts = access.split(".")
            if len(parts) == 3:
                payload = base64.b64decode(parts[1] + "==").decode()
                import json as j
                d = j.loads(payload)
                exp = d.get("exp")
                if exp:
                    print(f"[TOKEN] Expires: {t.strftime('%Y-%m-%d %H:%M:%S', t.localtime(exp))}")
                    print(f"[TOKEN] Expired: {t.time() > exp}")
        except Exception as e:
            print(f"[TOKEN] Could not decode: {e}")
    else:
        print("[SAVE] No access token found!")
        print(f"[SAVE] Full URL: {url[:500]}")


def main():
    print("=" * 60)
    print("  M-STOCK OAuth - Token Capture")
    print("=" * 60)

    # Start Flask in background
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print(f"\n[1] Server running on http://127.0.0.1:{PORT}")
    print("[2] Opening M-Stock login page in your browser...")

    # Build OAuth URL
    state = str(uuid.uuid4())
    login_url = (
        f"https://api.mstock.trade/openapi/typeb/connect/login"
        f"?clientCode=MA1116489"
        f"&response_type=code"
        f"&redirect_uri=http://127.0.0.1:{PORT}"
        f"&state={state}"
    )

    print(f"\n    If browser doesn't open automatically, go to:")
    print(f"    {login_url}")

    try:
        webbrowser.open(login_url)
        print("    Browser opened!")
    except Exception as e:
        print(f"    Could not open browser: {e}")

    print(f"\n[3] Complete login in browser:")
    print(f"    - Client Code: MA1116489")
    print(f"    - Password: RAJ123RAJ@r2")
    print(f"    - SMS OTP will arrive on your phone")
    print(f"    - Tokens will be captured automatically")
    print(f"\n    Waiting for redirect...")
    print(f"    (Press Ctrl+C to stop)\n")

    # Wait for redirect
    timeout = time.time() + 300
    while not _captured["done"] and time.time() < timeout:
        time.sleep(1)
        # Show a dot every 10 seconds
        if int(time.time()) % 10 == 0:
            print("    ... waiting for login ...")

    if _captured["done"]:
        print("\n[4] Redirect received!")
        save_tokens(_captured["data"])
        print("\n" + "=" * 60)
        print("  Done! Close this window.")
        print("=" * 60)
    else:
        print("\n[4] Timeout. No redirect received.")
        print("    Try again or check if the browser opened.")


if __name__ == "__main__":
    main()
