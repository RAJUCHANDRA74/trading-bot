"""
================================================================================
ZERODHA KITE CONNECT - COMPLETE AUTHENTICATION
================================================================================
Flow:
  1. Generate login URL
  2. Open in browser, user logs in + authorizes
  3. Redirect URL contains ?request_token=xxx
  4. Exchange request_token for access_token
  5. Save access_token to config
================================================================================
"""

import json, os, sys, webbrowser, time
from http.server import HTTPServer, BaseHTTPRequestHandler
import kiteconnect

# ── Load config ──────────────────────────────────────────────────────────────
config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path) as f:
    config = json.load(f)

API_KEY    = config['api_key']
API_SECRET = config['api_secret']
API_URL    = "https://api.kite.trade"

# ── Callback state ───────────────────────────────────────────────────────────
_request_token = None
_request_completed = False


class CallbackHandler(BaseHTTPRequestHandler):
    """Handle the redirect from Zerodha after user authorization."""

    def do_GET(self):
        global _request_token, _request_completed

        if _request_completed:
            return

        # Parse request_token from query string
        if '?' in self.path:
            query = self.path.split('?', 1)[1]
            params = dict(p.split('=', 1) for p in query.split('&') if '=' in p)
            _request_token = params.get('request_token', '')

        _request_completed = True

        # Send success response
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        html = """
        <html><body style="font-family:Arial; text-align:center; padding:60px; background:#f5f5f5;">
        <div style="background:white; border-radius:12px; padding:40px; max-width:400px; margin:0 auto; box-shadow:0 2px 12px rgba(0,0,0,0.1);">
            <h2 style="color:#28a745; margin:0 0 12px;">&#10004; Authorized!</h2>
            <p style="color:#555; font-size:16px; margin:0;">Your trading bot is now connected to Zerodha.</p>
            <p style="color:#888; font-size:14px; margin-top:20px;">You can close this window.</p>
        </div>
        </body></html>
        """
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # Suppress server logs


def start_callback_server(port=8765):
    """Start local HTTP server to receive the callback."""
    server = HTTPServer(('127.0.0.1', port), CallbackHandler)
    thread = __import__('threading').Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def authenticate():
    """Main authentication flow."""
    global _request_token

    kite = kiteconnect.KiteConnect(api_key=API_KEY)

    # ── Step 1: Generate login URL ──────────────────────────────────────────
    login_url = kite.login_url()
    print("="*60)
    print("  ZERODHA KITE CONNECT - AUTHENTICATION")
    print("="*60)
    print(f"\n[1] Login URL generated")
    print(f"    {login_url}\n")

    # ── Step 2: Start callback server ──────────────────────────────────────
    server = start_callback_server(8765)
    print(f"[2] Callback server running on http://127.0.0.1:8765")
    print(f"    (Waiting for Zerodha to redirect after you authorize...)\n")

    # ── Step 3: Open browser ───────────────────────────────────────────────
    print("[3] Opening browser for Zerodha login...")
    webbrowser.open(login_url)

    # ── Step 4: Wait for callback ──────────────────────────────────────────
    print("[4] Waiting for you to log in and authorize...")
    print("    - A browser window should have opened")
    print("    - Log in to Zerodha with your credentials")
    print("    - Click 'Allow' to authorize this app")
    print("    - The page will show 'Authorized!' when done\n")

    timeout = time.time() + 300  # 5 minutes
    while not _request_completed and time.time() < timeout:
        time.sleep(1)

    server.shutdown()

    if not _request_token:
        print("[ERROR] No request token received within 5 minutes.")
        print("        Try again and authorize more quickly.")
        return None

    print(f"[5] Got request token: {_request_token[:10]}... ")

    # ── Step 5: Exchange for access token ──────────────────────────────────
    print("[6] Exchanging request token for access token...")
    try:
        data = kite.generate_session(_request_token, api_secret=API_SECRET)
        access_token = data['data']['access_token']

        print(f"\n    User:       {data['data'].get('user_name', 'N/A')}")
        print(f"    User ID:    {data['data'].get('user_id', 'N/A')}")
        print(f"    Access Tkn: {access_token[:20]}...")

        # Save to config
        config['access_token'] = access_token
        config['public_token'] = _request_token
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)

        print("\n[SAVED] Access token saved to config.json")

        # ── Step 6: Test ───────────────────────────────────────────────────
        kite.set_access_token(access_token)
        profile = kite.get_profile()
        print(f"\n[SUCCESS] Connected as: {profile.get('user_name')} ({profile.get('email')})")

        # Check margins
        margins = kite.get_margins()
        for seg, data in margins.items():
            equity = data.get('equity', {})
            available = equity.get('available', {})
            print(f"    {seg.upper()}: Cash = ₹{available.get('cash', 0):,.0f}, "
                  f"Open P&L = ₹{available.get('payin', 0):,.0f}")

        return access_token

    except Exception as e:
        print(f"\n[ERROR] Session exchange failed: {e}")
        return None


if __name__ == "__main__":
    result = authenticate()
    if not result:
        sys.exit(1)
