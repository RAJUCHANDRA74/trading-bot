import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()
text = raw.decode('utf-8')

lines = text.split('\n')
print(f"Total lines: {len(lines)}")
print(f"Line 1 (empty): {lines[0] == ''}")
print(f"Line 2 (empty): {lines[1] == ''}")
print(f"Line 3 starts with /*: {lines[2].startswith('/*')}")

# Count braces/parens/brackets
for name, open_c, close_c in [('braces', '{', '}'), ('parens', '(', ')'), ('brackets', '[', ']')]:
    o = text.count(open_c)
    c = text.count(close_c)
    print(f"{name}: {o} open, {c} close, diff={o-c}")

# Check: odd number of backticks in the last 100 chars
last100 = text[-100:]
bt_last100 = last100.count('\u0060')
print(f"\nBackticks in last 100 chars: {bt_last100}")

# Backtick positions
bt_positions = [i for i, ch in enumerate(text) if ch == '\u0060']
print(f"Total backticks: {len(bt_positions)}")

# If odd number of backticks, the last one opens a template
if len(bt_positions) % 2 == 1:
    last_bt = bt_positions[-1]
    remaining = text[last_bt:]
    print(f"\n!!! Odd backticks ({len(bt_positions)}). Last at char {last_bt}")
    print(f"Remaining from last backtick ({len(remaining)} chars): {remaining[:100]!r}")
    print(f"Ending: {remaining[-50:]!r}")
else:
    print(f"\nEven number of backticks ({len(bt_positions)})")
    last_bt = bt_positions[-1]
    print(f"Last backtick at char {last_bt}: {text[last_bt:last_bt+30]!r}")

# Also check: what if the LAST backtick opens a template?
# Count backticks in last 500 chars
last500 = text[-500:]
bt_last500 = last500.count('\u0060')
print(f"\nBackticks in last 500 chars: {bt_last500}")

# Count total backticks in the ENTIRE text
bt_all = text.count('\u0060')
print(f"All backticks: {bt_all}")

# Pair them up
in_template = False
opens = []
closes = []
for i, ch in enumerate(text):
    if ch == '\u0060':
        if not in_template:
            in_template = True
            opens.append(i)
        else:
            in_template = False
            closes.append(i)

print(f"\nOpens: {len(opens)}, Closes: {len(closes)}")
if len(opens) > len(closes):
    print(f"UNCLOSED: {len(opens) - len(closes)}")
    print(f"First unclosed at char {opens[len(closes)]}:")
    ctx = text[opens[len(closes)]:opens[len(closes)]+200]
    print(f"  Content: {ctx!r}")
    line_num = text[:opens[len(closes)]].count('\n') + 1
    print(f"  Line: {line_num}")
