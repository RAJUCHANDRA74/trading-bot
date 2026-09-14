import urllib.request

url = "http://127.0.0.1:8765/"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

text = body.decode('utf-8')
lines = text.split('\n')

# Show lines 975-987
print("=== Lines 975-987 ===")
for i in range(974, len(lines)):
    clean = lines[i].replace('\u20b9','Rs').replace('\u25cf','*')
    print("Line", i+1, ":", repr(clean[:150]))
