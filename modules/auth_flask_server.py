"""
================================================================================
M-STOCK - Flask Token Server
================================================================================
Opens M-Stock login in browser, captures tokens via redirect URL.
Flow:
  1. Start Flask server on port 5555
  2. Open M-Stock login page with redirect to localhost:5555
  3. User logs in (SMS OTP works!)
  4. M-Stock redirects to our server with tokens
  5. Server captures tokens and saves to config.json
================================================================================
"""

import json, os, sys
from flask import Flask, request, redirect
import threading
import time
import webbrowser
import requests

app = Flask(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
API_KEY = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="
PORT = 5555

# Global storage for captured data
_captured = {"done": False, "data": None}


@app.route("/")
def callback():
    """Handle the redirect from M-Stock."""
    print(f"\n    *** REDIRECT RECEIVED ***")
    print(f"    URL: {request.url}")
    print(f"    Args: {dict(request.args)}")

    # Extract tokens from URL
    args = dict(request.args)

    # Look for various token formats
    token = args.get("access_token") or args.get("token") or args.get("jwtToken") or args.get("jwt_token")
    auth = args.get("Auth") or args.get("auth")
    refresh = args.get("refresh_token") or args.get("refreshToken") or args.get("refresh")
    feed = args.get("feedToken") or args.get("feed_token")

    # If the whole URL contains tokens, parse it
    url = request.url
    if not token and "token" in url.lower():
        import re
        tmatch = re.search(r'[?&](?:access_token|token|jwtToken|jwt_token)=([^&]+)', url)
        if tmatch:
            token = tmatch.group(1)

    _captured["data"] = {
        "access_token": token or auth,
        "refresh_token": refresh,
        "feed_token": feed,
        "url": url,
        "args": args
    }

    # Return success page
    return """
    <html><body style="font-family:Arial; text-align:center; padding:60px; background:#e8f5e9;">
    <div style="background:white; border-radius:12px; padding:40px; max-width:500px; margin:0 auto; box-shadow:0 2px 12px rgba(0,0,0,0.1);">
        <h2 style="color:#2e7d32; margin:0 0 12px;">&#10004; Connected!</h2>
        <p style="color:#555; font-size:16px; margin:0;">Your trading bot is now connected to M-Stock.</p>
        <p style="color:#888; font-size:14px; margin-top:20px;">You can close this window.</p>
    </div>
    </body></html>
    """


@app.route("/health")
def health():
    return "OK"


def run_server():
    """Run Flask server."""
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def main():
    print("="*60)
    print("  M-STOCK - FLASK TOKEN SERVER")
    print("="*60)

    # Start Flask server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print(f"\n[1] Server running on http://127.0.0.1:{PORT}")

    # Generate login URL with redirect
    login_url = (
        f"https://api.mstock.trade/openapi/typeb/connect/login"
        f"?clientCode=MA1116489"
        f"&redirect_url=http://127.0.0.1:{PORT}"
    )

    print(f"\n[2] Opening M-Stock login page...")
    print(f"    URL: {login_url}")

    # Try opening browser
    try:
        webbrowser.open(login_url)
        print(f"    Browser opened!")
    except Exception as e:
        print(f"    Could not open browser automatically.")
        print(f"    Please manually open this URL: {login_url}")

    print(f"\n[3] Waiting for M-Stock redirect...")
    print(f"    In the browser:")
    print(f"    - Log in with Client Code: MA1116489")
    print(f"    - Password: RAJ123RAJ@r2")
    print(f"    - Enter SMS OTP (arrives immediately!)")
    print(f"    - Complete login")
    print(f"    - Browser will redirect to this server")
    print(f"    - Tokens will be captured automatically")
    print(f"\n    Waiting...")

    # Wait for redirect (max 5 minutes)
    timeout = time.time() + 300
    while not _captured["done"] and time.time() < timeout:
        time.sleep(1)

    if _captured["done"]:
        print("\n[4] Tokens captured!")
        save_tokens(_captured["data"])
    else:
        print("\n[4] Timeout — no redirect received.")
        print("    Try opening the URL manually or check browser.")


def save_tokens(data):
    """Save captured tokens and test connection."""
    if not data:
        return

    access = data.get("access_token") or data.get("Auth")
    refresh = data.get("refresh_token")
    feed = data.get("feed_token")

    print(f"\n    Access token: {str(access)[:30] if access else 'NONE'}...")
    print(f"    Refresh token: {str(refresh)[:30] if refresh else 'NONE'}...")

    if access:
        # Save to config
        cfg = json.load(open(CONFIG_PATH))
        cfg["access_token"] = access
        if refresh:
            cfg["refresh_token"] = refresh
        if feed:
            cfg["feed_token"] = feed
        json.dump(cfg, open(CONFIG_PATH, "w"), indent=4)
        print("\n    [SAVED] Tokens saved to config.json")

        # Test
        import requests as req
        r = req.get(
            "https://api.mstock.trade/openapi/typeb/user/fundsummary",
            headers={
                "X-Mirae-Version": "1",
                "Authorization": f"Bearer {access}",
                "X-PrivateKey": API_KEY
            },
            timeout=15
        )
        print(f"\n    API Test: {r.status_code} | {r.text[:200]}")

        if r.status_code == 200:
            print("\n" + "="*60)
            print("  M-STOCK CONNECTED!")
            print("="*60)
        else:
            print("\n    Token saved but API rejected it")
            print("    The token may be browser-only")
    else:
        print("\n    No access token found in redirect URL")
        print(f"    Full redirect data: {data}")


if __name__ == "__main__":
    main()
