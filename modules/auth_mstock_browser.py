"""
================================================================================
M-STOCK - BROWSER AUTOMATION WITH TOKEN INTERCEPT
================================================================================
Opens M-Stock in browser, intercepts the API call that returns tokens.
SMS OTP works through browser (user confirmed).
================================================================================
"""

import json, os
from playwright.sync_api import sync_playwright

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
CLIENT_CODE = "MA1116489"
PASSWORD    = "RAJ123RAJ@r2"
API_KEY     = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="

_captured_tokens = {}


def main():
    print("="*60)
    print("  M-STOCK - BROWSER LOGIN WITH TOKEN CAPTURE")
    print("="*60)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        # ── Intercept API responses ──────────────────────────────────────
        def handle_response(response):
            url = response.url
            if 'api.mstock.trade' in url or 'mstock' in url.lower():
                try:
                    body = response.text()
                    if 'jwtToken' in body or 'access_token' in body.lower() or 'refreshToken' in body:
                        print(f"\n  *** CAPTURED API RESPONSE ***")
                        print(f"  URL: {url}")
                        print(f"  Body: {body[:500]}")
                        _captured_tokens['response'] = body
                        _captured_tokens['url'] = url
                except:
                    pass

        page.on("response", handle_response)

        print("\n[1] Opening M-Stock login page...")
        page.goto("https://trade.mstock.com", timeout=60000)
        page.wait_for_load_state('domcontentloaded', timeout=30000)
        print(f"  URL: {page.url}")

        print("""
\n[2] BROWSER IS NOW OPEN!

  In the browser window:
  1. Click "Login" or "Sign In"
  2. Enter Client Code: MA1116489
  3. Enter Password: RAJ123RAJ@r2
  4. Click "Login" — SMS OTP will arrive IMMEDIATELY!
  5. Enter the 6-digit OTP from your phone
  6. Complete login until you see the dashboard

  Come back here and press Enter after you see the dashboard.
        """)

        input("\n  Press Enter after completing browser login...")

        # Check captured tokens
        if 'response' in _captured_tokens:
            print("\n[3] SUCCESS! Found tokens in intercepted response!")
            try:
                import re
                body = _captured_tokens['response']
                # Extract JWT token
                match = re.search(r'"jwtToken"\s*:\s*"([^"]+)"', body)
                if match:
                    jwt = match.group(1)
                    print(f"  JWT Token: {jwt[:50]}...")

                    # Extract refresh token
                    match2 = re.search(r'"refreshToken"\s*:\s*"([^"]+)"', body)
                    refresh = match2.group(1) if match2 else ''
                    print(f"  Refresh Token: {refresh[:50]}...")

                    # Save to config
                    cfg = json.load(open(CONFIG_PATH))
                    cfg['access_token'] = jwt
                    cfg['refresh_token'] = refresh
                    json.dump(cfg, open(CONFIG_PATH, 'w'), indent=4)
                    print("\n  [SAVED] Tokens saved to config.json!")
                    print("\n[M-STOCK CONNECTED!]")

                    # Test the token
                    import requests
                    r = requests.get(
                        'https://api.mstock.trade/openapi/typeb/user/fundsummary',
                        headers={
                            'X-Mirae-Version': '1',
                            'Authorization': f'Bearer {jwt}',
                            'X-PrivateKey': API_KEY
                        },
                        timeout=15
                    )
                    print(f"\n  API Test: {r.status_code} | {r.text[:300]}")

                    browser.close()
                    return
            except Exception as e:
                print(f"  Parse error: {e}")

        # No tokens captured — try extracting from page
        print("\n[3] No token captured via interception.")
        print("    Trying to extract from page...")

        try:
            storage = page.evaluate("""() => {
                let data = {};
                for (let i = 0; i < localStorage.length; i++) {
                    let k = localStorage.key(i);
                    data[k] = localStorage.getItem(k);
                }
                return data;
            }""")
            for k, v in storage.items():
                if any(x in k.lower() for x in ['token', 'jwt', 'auth', 'access']):
                    print(f"  {k}: {str(v)[:80]}")
        except Exception as e:
            print(f"  Storage error: {e}")

        print("""
\n  If tokens were found above, great!
  Otherwise, the browser login may use a different auth system.

  Your M-Stock account tokens may only work in the browser context,
  not via the Type B API directly.
        """)

        browser.close()


if __name__ == "__main__":
    main()
