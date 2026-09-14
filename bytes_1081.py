import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()
text = raw.decode('utf-8')
lines = text.split('\n')

line = lines[1080]  # 0-indexed = line 1081
print("Length:", len(line))

# Find all backtick positions
bt_positions = [i for i, c in enumerate(line) if c == '\u0060']
print("Backtick positions:", bt_positions)
print("Number of backticks:", len(bt_positions))

# For each backtick, show context
for pos in bt_positions:
    ctx_start = max(0, pos-5)
    ctx_end = min(len(line), pos+20)
    print("  Backtick at pos %3d: ...%r..." % (pos, line[ctx_start:ctx_end]))

# Find the FIRST { after each backtick (these are the ones counted)
print("\nFirst { after each backtick:")
for bt in bt_positions:
    for j in range(bt+1, len(line)):
        c = line[j]
        if c == ' ' or c == '\t':
            continue
        if c == '{':
            ctx = line[max(0,j-20):j+10]
            print("  Backtick at %d: first non-space char is '{' at pos %d: %r" % (bt, j, ctx))
            break
        elif c == '\n':
            print("  Backtick at %d: no more content on line" % bt)
            break
        else:
            ctx = line[max(0,j-20):j+10]
            print("  Backtick at %d: first non-space char is '%s' at pos %d: %r" % (bt, c, j, ctx))
            break
