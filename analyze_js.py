import urllib.request

# Download the actual served file
r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()

print(f"Fetched {len(raw)} bytes")
print(f"Content-Type: {r.headers.get('Content-Type')}")
print(f"First 50 bytes: {raw[:50]}")
print(f"Last 50 bytes: {raw[-50:]}")
print()

# Check for BOM
if raw.startswith(b'\xef\xbb\xbf'):
    print("WARNING: UTF-8 BOM at start!")
else:
    print("No BOM at start")
print(f"First 3 bytes: {raw[:3]}")

# Count backticks
backtick_count = raw.count(b'\x60')
print(f"\nBackticks: {backtick_count}")

# Check for null bytes
null_count = raw.count(b'\x00')
print(f"Null bytes: {null_count}")

# Check for </script anywhere
slash_script = b'</scr'
positions = [m.start() for m in __import__('re').finditer(slash_script, raw)]
print(f"</scr positions: {positions}")

# Decode as UTF-8
text = raw.decode('utf-8', errors='replace')
print(f"\nDecoded as UTF-8: {len(text)} chars")

# Check for replacement chars
repl = text.count('\ufffd')
print(f"Replacement chars: {repl}")

# The critical test: find ALL backtick positions
backtick_positions = [m.start() for m in __import__('re').finditer('\x60', text)]
print(f"\nBacktick positions (first 10): {backtick_positions[:10]}")
print(f"Backtick positions (last 10): {backtick_positions[-10:]}")

# Count open/closed templates
in_template = False
open_count = 0
closed_count = 0
open_positions = []
closed_positions = []

for pos in backtick_positions:
    if not in_template:
        in_template = True
        open_count += 1
        open_positions.append(pos)
    else:
        in_template = False
        closed_count += 1
        closed_positions.append(pos)

print(f"\nTemplates: {closed_count} closed, {open_count} open")
if open_positions:
    print(f"First open template at char {open_positions[0]}: {repr(text[max(0,open_positions[0]-30):open_positions[0]+50])}")
    print(f"Last 50 chars of file: {repr(text[-50:])}")

# Check for unclosed strings (including regular strings)
in_string = False
string_char = None
escaped = False

for i, c in enumerate(text):
    if escaped:
        escaped = False
        continue
    if c == '\\':
        escaped = True
        continue
    if not in_string:
        if c in ('"', "'"):
            in_string = True
            string_char = c
            str_start = i
    else:
        if c == string_char:
            in_string = False

if in_string:
    line_num = text[:str_start].count('\n') + 1
    print(f"\nUNCLOSED STRING at line {line_num}: {repr(text[max(0,str_start-20):str_start+50])}")
else:
    print("\nNo unclosed strings")

# Double-check: try to find the LAST unmatched backtick
# (the one that causes the "unexpected end")
if open_positions and not in_template:
    # Last opened but not yet closed
    last_open = open_positions[-1]
    print(f"\nLast opened template at char {last_open}:")
    print(f"Content from there: {repr(text[last_open:last_open+100])}")
    line_num = text[:last_open].count('\n') + 1
    print(f"Starts at line {line_num}")

# Try: what if the very first backtick is unmatched?
first_backtick = backtick_positions[0] if backtick_positions else -1
print(f"\nFirst backtick at char {first_backtick}")
if first_backtick >= 0:
    ctx = text[max(0, first_backtick-20):first_backtick+50]
    print(f"Context: {repr(ctx)}")
