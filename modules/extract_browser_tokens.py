"""
Extract tokens from browser localStorage.
Run this to check if any tokens were stored.
"""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    # Try to connect to existing browser
    browsers = []
    for browser_type in ['chromium', 'firefox', 'webkit']:
        try:
            b = getattr(p, browser_type).connect_over_cdp("http://localhost:9222")
            contexts = b.contexts
            for ctx in contexts:
                for page in ctx.pages:
                    try:
                        storage = page.evaluate("""() => {
                            let data = {};
                            for (let i = 0; i < localStorage.length; i++) {
                                let k = localStorage.key(i);
                                let v = localStorage.getItem(k);
                                if (k.toLowerCase().includes('token') ||
                                    k.toLowerCase().includes('jwt') ||
                                    k.toLowerCase().includes('auth') ||
                                    k.toLowerCase().includes('access') ||
                                    k.toLowerCase().includes('mstock')) {
                                    data[k] = String(v).substring(0, 100);
                                }
                            }
                            return data;
                        }""")
                        if storage:
                            print(f"Found tokens in {browser_type} browser:")
                            for k, v in storage.items():
                                print(f"  {k}: {v}")
                        else:
                            print(f"No token-related keys in {browser_type} localStorage")
                    except Exception as e:
                        print(f"Error reading {browser_type}: {e}")
            b.close()
        except Exception as e:
            print(f"Could not connect to {browser_type}: {e}")
