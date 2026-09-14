"""Fix brace counting — handle template literals properly."""
import re

data = open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/index.html', 'rb').read()

matches = list(re.finditer(b'<script[^>]*>(.*?)</script>', data, re.DOTALL))
js_bytes = matches[-1].group(1)
js = js_bytes.decode('utf-8', errors='replace')

print(f'JS chars: {len(js)}', flush=True)

# Proper brace counter: treat template literal interpolations as string content
depth = 0
max_depth = 0
max_pos = 0
in_str = False
str_char = None
in_tpl = False

for idx, ch in enumerate(js):
    if in_str:
        if ch == '\\':
            idx += 1  # skip escaped char
        elif ch == str_char:
            in_str = False
    elif in_tpl:
        if ch == '\\':
            idx += 1
        elif ch == '`':
            in_tpl = False
        elif ch == '$' and idx + 1 < len(js) and js[idx+1] == '{':
            # ${} inside template literal — NOT a real block, skip content
            # Find matching }
            j = idx + 2
            tpl_depth = 1
            while j < len(js) and tpl_depth > 0:
                c = js[j]
                if c == '\\':
                    j += 2
                    continue
                elif c == '`':
                    # End of template literal (unbalanced — shouldn't happen)
                    in_tpl = False
                    break
                elif c == '{':
                    tpl_depth += 1
                elif c == '}':
                    tpl_depth -= 1
                j += 1
            idx = j - 1  # will be incremented by for loop
    else:
        if ch in '"\'':
            in_str = True
            str_char = ch
        elif ch == '`':
            in_tpl = True
        elif ch == '{':
            depth += 1
            if depth > max_depth:
                max_depth = depth
                max_pos = idx
        elif ch == '}':
            depth -= 1
    
    # Safety limit
    if idx >= len(js) - 1:
        break

print(f'Brace depth at end: {depth}', flush=True)
print(f'Max depth: {max_depth} at char {max_pos}', flush=True)

# If unclosed, show context around the first unmatched {
if depth > 0:
    print(f'\nScanning for unclosed blocks...', flush=True)
    depth2 = 0
    in_str = False
    str_char = None
    in_tpl = False
    for idx, ch in enumerate(js):
        if in_str:
            if ch == '\\': idx += 1
            elif ch == str_char: in_str = False
        elif in_tpl:
            if ch == '\\': idx += 1
            elif ch == '`': in_tpl = False
            elif ch == '$' and idx + 1 < len(js) and js[idx+1] == '{':
                j = idx + 2
                tpl_depth = 1
                while j < len(js) and tpl_depth > 0:
                    c = js[j]
                    if c == '\\': j += 2
                    elif c == '{': tpl_depth += 1
                    elif c == '}': tpl_depth -= 1
                    j += 1
                idx = j - 1
        else:
            if ch in '"\'': in_str = True; str_char = ch
            elif ch == '`': in_tpl = True
            elif ch == '{': depth2 += 1
            elif ch == '}': depth2 -= 1
        
        if idx >= len(js) - 1: break
    
    print(f'Final depth (simple scan): {depth2}', flush=True)
