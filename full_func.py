import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()
text = raw.decode('utf-8')
lines = text.split('\n')

# Show full function with braces
print("=== renderTlChart function (lines 1036-1126) ===")
for i in range(1035, 1126):
    line = lines[i]
    shown = line.expandtabs(2)
    shown = shown.replace('{', '[{]').replace('}', '[}]')
    print("%4d: %s" % (i+1, shown))
