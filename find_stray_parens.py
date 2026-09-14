import urllib.request

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

text = body.decode('utf-8', errors='replace')
lines = text.split('\n')

# Find lines that are just ')'
print("Lines that are just ')' :")
for i, line in enumerate(lines):
    if line.strip() == ')':
        print("  Line " + str(i+1))

# Lines ending with ) that are NOT method chains
EXCLUDE = ['forEach', '=>', '.map(', '.filter(', '.reduce(', 'join(', '.some(', '.every(', '.find(', '.findIndex(', 'return ', 'throw ', ')(']

print("\nSuspicious lines ending with ')':")
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.endswith(')') and not any(x in stripped for x in EXCLUDE):
        # Skip comment-only or mostly whitespace lines
        if not stripped.startswith('//') and not stripped.startswith('*'):
            print("  Line " + str(i+1) + ": " + stripped[:80])
            if i > 0:
                print("    Prev: " + lines[i-1].strip()[:80])

# Lines that are just '});'
print("\nLines that are just '});' (standalone):")
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == '});':
        prev = lines[i-1].strip() if i > 0 else ''
        if prev.endswith(')') or prev.endswith("'") or prev.endswith('"'):
            print("  Line " + str(i+1) + ": prev='" + prev[-40:] + "'")

# Check for function definitions with ) in wrong place
print("\nFunctions with '=> )' pattern:")
for i, line in enumerate(lines):
    if '=> )' in line or '=>)' in line:
        print("  Line " + str(i+1) + ": " + line.strip()[:80])
