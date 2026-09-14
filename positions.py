import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()
text = raw.decode('utf-8')
lines = text.split('\n')

line = lines[1080]
print("Line length:", len(line))
print()

# Find ALL interesting positions
interesting = {}
for i, c in enumerate(line):
    if c in ('{', '}', '`', '$', "'", '"', '\\'):
        ctx = line[max(0,i-3):i+4]
        interesting[i] = (c, ctx)

# Print key sections
print("Around position 30-45:")
for i in range(28, 50):
    if i in interesting:
        c, ctx = interesting[i]
        print("  pos %3d: %r  context: %r" % (i, c, ctx))
    else:
        print("  pos %3d: %r" % (i, line[i]))

print()
print("Around position 440-460:")
for i in range(438, 462):
    if i in interesting:
        c, ctx = interesting[i]
        print("  pos %3d: %r  context: %r" % (i, c, ctx))
    else:
        print("  pos %3d: %r" % (i, line[i]))
