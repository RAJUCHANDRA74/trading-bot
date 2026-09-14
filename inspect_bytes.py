import urllib.request

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

# First 50 bytes as hex
print("First 50 bytes (hex):")
for i in range(min(50, len(body))):
    print("%02X" % body[i], end=' ')
    if (i + 1) % 16 == 0:
        print()

# Check for BOM
if body[:3] == b'\xef\xbb\xbf':
    print("\nWARNING: UTF-8 BOM found at start!")
else:
    print("\nNo BOM at start")

# Check last 20 bytes
print("\nLast 20 bytes (hex):")
for i in range(max(0, len(body)-20), len(body)):
    print("%02X" % body[i], end=' ')
print()

# Decode first 5 lines
text = body.decode('utf-8')
lines = text.split('\n')
print("\nFirst 5 lines:")
for i in range(min(5, len(lines))):
    print(repr(lines[i]))
