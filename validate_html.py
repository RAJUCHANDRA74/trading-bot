"""Extract and validate ALL JavaScript from HTML."""
import re, sys

with open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/index.html', 'rb') as f:
    data = f.read()

script_blocks = list(re.finditer(b'<script(?:[^>]*)>(.*?)</script>', data, re.DOTALL))
print(f'Found {len(script_blocks)} script block(s)', flush=True)

for i, m in enumerate(script_blocks):
    js_bytes = m.group(1)
    js = js_bytes.decode('utf-8', errors='replace')
    tag = m.group(0)[:30]
    print(f'\nScript {i+1}: {len(js)} chars', flush=True)
    print(f'  Tag: {repr(tag)}', flush=True)
    
    # Last script block = main JS
    if i == len(script_blocks) - 1:
        # Count structures
        b_open = js.count('{')
        b_close = js.count('}')
        p_open = js.count('(')
        p_close = js.count(')')
        br_open = js.count('[')
        br_close = js.count(']')
        
        print(f'  Braces: {b_open}/{b_close} (diff={b_open-b_close})', flush=True)
        print(f'  Parens: {p_open}/{p_close} (diff={p_open-p_close})', flush=True)
        print(f'  Brackets: {br_open}/{br_close} (diff={br_open-br_close})', flush=True)
        
        # Key functions
        for fn in ['attemptLogin', 'init', 'connectWS', 'renderTradeLog', 'renderStrategies']:
            print(f'  {fn}: {"YES" if fn in js else "MISSING"}', flush=True)
        
        # The critical check: does JS end properly?
        last_chars = js[-50:]
        print(f'  Last 50 chars: {repr(last_chars)}', flush=True)
        
        # Check for unclosed template literals
        backticks = js.count('`')
        print(f'  Backticks: {backticks} ({backticks % 2} orphan)', flush=True)
        
        # Check for suspicious </script inside JS
        if '</script' in js.lower():
            print('  WARNING: Found </script in JS!', flush=True)
            idx = js.lower().find('</script')
            print(f'    At: {repr(js[max(0,idx-30):idx+30])}', flush=True)
