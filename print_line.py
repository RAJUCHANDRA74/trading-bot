import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')
r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
text = r.read().decode('utf-8')
lines = text.split('\n')
# Print lines 1077-1096 (0-indexed: 1076-1095)
for i in range(1076, 1096):
    print("Line %d: %s" % (i+1, repr(lines[i])))
