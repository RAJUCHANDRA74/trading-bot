import urllib.request, re

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

text = body.decode('utf-8')
lines = text.split('\n')

with open('served_dashboard.js', 'wb') as f:
    f.write(body)

print("File lines:", len(lines))

# Pattern 1: ==) or ===) - comparison missing right operand
matches = list(re.finditer(r'(={2,3})\s*\)', text))
print("Pattern 1 (==) or ===) followed by ):", len(matches))
for m in matches:
    line_num = text[:m.start()].count('\n') + 1
    snippet = text[max(0,m.start()-50):m.end()+50].replace('\n',' | ')
    print("  Line", line_num, ":", snippet[:150])

# Pattern 2: } ) - closing brace immediately followed by close paren
print("\nPattern 2 (} ) patterns):")
for i, line in enumerate(lines):
    stripped = line.strip()
    if re.search(r'}\s*\)', stripped):
        if not any(x in stripped for x in ['.forEach', '=>', 'map(', '.filter', '.reduce']):
            clean = stripped.replace('\u20b9','Rs').replace('\u25cf','*')
            print("  Line", i+1, ":", clean[:120])

# Pattern 3: Bare ) on its own line
print("\nBare ) lines:")
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == ')' or stripped == ') }' or stripped == '})':
        clean = stripped.replace('\u20b9','Rs').replace('\u25cf','*')
        print("  Line", i+1, ":", clean)

# Pattern 4: Double close paren
print("\nDouble close paren patterns (first 5):")
matches = list(re.finditer(r'\)\s*\)', text))
for m in matches[:5]:
    line_num = text[:m.start()].count('\n') + 1
    snippet = text[max(0,m.start()-30):m.end()+30].replace('\n',' | ')
    print("  Line", line_num, ":", snippet[:100])

# Pattern 5: First 10 lines
print("\n=== First 10 lines ===")
for i in range(min(10, len(lines))):
    clean = lines[i].replace('\u20b9','Rs').replace('\u25cf','*')
    print("%3d: %s" % (i+1, clean))
