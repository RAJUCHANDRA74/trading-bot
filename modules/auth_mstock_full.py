"""
M-STOCK - Complete browser automation with token extraction.
Intercepts network responses and reads localStorage.
"""
import json, os, re
from playwright.sync_api import sync_playwright

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
API_KEY = "G+gwomhRoY0yHoPVwg/Lh2RihJcXZgm5TcXmY1dS3+Y="

_captured = {}

def main():
    print("="*60)
    print("  M-STOCK - COMPLETE LOGIN")
    print("="*60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1400, 'height': 900})
        page = context.new_page()

        # Intercept all API responses
        def on_response(response):
            try:
                if 'api.mstock' in response.url or 'mstock' in response.url:
                    body = response.text()
                    if any(x in body for x in ['jwtToken', 'jwt', 'access_token', 'refreshToken']):
                        print(f"\n    *** API RESPONSE CAPTURED ***")
                        print(f"    URL: {response.url[:80]}")
                        print(f"    Body: {body[:300]}")
                        _captured.update({'url': response.url, 'body': body})
            except:
                pass

        page.on("response", on_response)

        print("\n[1] Opening M-Stock...")
        page.goto("https://trade.mstock.com", timeout=60000)
        print(f"    URL: {page.url}")

        print("""
\n[2] LOG IN IN THE BROWSER NOW!
    - Enter Client Code: MA1116489
    - Enter Password: RAJ123RAJ@r2
    - Enter SMS OTP (arrives immediately!)
    - Complete login to dashboard
    - Then press Enter here
    """)

        input("    Press Enter after dashboard appears: ")

        print("\n[3] Extracting tokens...")

        # Read localStorage
        storage = page.evaluate("""() => {
            let data = {};
            try {
                for (let i = 0; i < localStorage.length; i++) {
                    let k = localStorage.key(i);
                    data['ls_' + k] = localStorage.getItem(k);
                }
            } catch(e) { data['error'] = e.message; }
            try {
                for (let i = 0; i < sessionStorage.length; i++) {
                    let k = sessionStorage.key(i);
                    data['ss_' + k] = sessionStorage.getItem(k);
                }
            } catch(e) {}
            return data;
        }""")

        print(f"    Found {len(storage)} storage items")
        for k, v in storage.items():
            if any(x in k.lower() for x in ['token', 'jwt', 'auth', 'access', 'mstock', 'user']):
                print(f"    {k}: {str(v)[:100]}")

        # Also read cookies
        cookies = context.cookies()
        print(f"\n    Cookies: {len(cookies)}")
        for c in cookies:
            if any(x in c['name'].lower() for x in ['token', 'jwt', 'auth', 'session']):
                print(f"    {c['name']}: {c['value'][:50]}")

        # Parse captured response
        if 'body' in _captured:
            print("\n[4] Parsing captured API response...")
            body = _captured['body']
            jwt_match = re.search(r'"jwtToken"\s*:\s*"([^"]+)"', body)
            refresh_match = re.search(r'"refreshToken"\s*:\s*"([^"]+)"', body)
            feed_match = re.search(r'"feedToken"\s*:\s*"([^"]+)"', body)

            jwt = jwt_match.group(1) if jwt_match else None
            refresh = refresh_match.group(1) if refresh_match else None
            feed = feed_match.group(1) if feed_match else None

            if jwt:
                print(f"    JWT: {jwt[:50]}...")
                cfg = json.load(open(CONFIG_PATH))
                cfg['access_token'] = jwt
                cfg['refresh_token'] = refresh or cfg.get('refresh_token', '')
                cfg['feed_token'] = feed or cfg.get('feed_token', '')
                json.dump(cfg, open(CONFIG_PATH, 'w'), indent=4)

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
                print(f"\n    API Test: {r.status_code} | {r.text[:200]}")

                if r.status_code == 200:
                    print("\n" + "="*60)
                    print("  M-STOCK CONNECTED!")
                    print("="*60)
                else:
                    print("\n    Token captured but API rejected it (may be browser-only token)")
                    print("    Trying refresh token...")

            else:
                print("    No JWT found in captured response")
                print(f"    Captured body: {body[:200]}")
        else:
            print("\n    No API response with tokens captured")
            print("    You may need to trigger the API call in browser")

        browser.close()

if __name__ == "__main__":
    main()
