import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()
text = raw.decode('utf-8')
lines = text.split('\n')

print("=== Lines 1044-1068 with brace markers ===")
for i in range(1043, 1068):
    line = lines[i]
    shown = line.replace('\t', '  ')
    # Mark braces
    shown = shown.replace('{', '[{]').replace('}', '[}]')
    print("%4d: %s" % (i+1, shown))
