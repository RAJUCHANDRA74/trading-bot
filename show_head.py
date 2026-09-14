import urllib.request

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

text = body.decode('utf-8')
lines = text.split('\n')

print("Total lines:", len(lines))

# Check first 10 lines
print("\n=== First 10 lines ===")
for i in range(min(10, len(lines))):
    line = lines[i]
    # Show char codes
    char_codes = [(j, ord(c)) for j, c in enumerate(line) if ord(c) > 127 or ord(c) < 32]
    snippet = repr(line[:100])
    print("Line", i+1, "(len=", len(line), "):", snippet[:100])
    if char_codes:
        print("  Special chars:", char_codes[:5])

# Check for any BOM
print("\nFirst 5 bytes (hex):", body[:5].hex())
