import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()
text = raw.decode('utf-8')
lines = text.split('\n')

line = lines[1080]
print("Line 1081 first 100 chars (raw bytes):")
print(repr(line[:100]))
print()
print("Char codes for first 30:")
for i, c in enumerate(line[:30]):
    print("  pos %2d: ord=%3d char=%r" % (i, ord(c), c))
