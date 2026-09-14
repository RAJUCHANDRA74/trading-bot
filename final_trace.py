import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()
text = raw.decode('utf-8')
lines = text.split('\n')

func_start = 1035
func_end = 1126
backtick = '\u0060'

depth = 0
in_tmpl = False

print("=== Corrected full-state-machine trace ===")
for ln_idx in range(func_start, func_end + 1):
    line = lines[ln_idx]
    line_num = ln_idx + 1
    prev = depth
    i = 0

    while i < len(line):
        c = line[i]

        if c == '\\':
            # Skip backslash + next char (escape sequence)
            i += 2
            continue

        # Multi-line comment
        if c == '/' and i+1 < len(line) and line[i+1] == '*':
            end = line.find('*/', i+2)
            if end >= 0:
                i = end + 2
            else:
                break
            continue

        # Single-line comment
        if c == '/' and i+1 < len(line) and line[i+1] == '/':
            break

        if not in_tmpl:
            if c == backtick:
                in_tmpl = True
                i += 1
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
        else:
            if c == backtick:
                in_tmpl = False
                i += 1
                continue
            if c == '$' and i+1 < len(line) and line[i+1] == '{':
                # Enter template expression: parse JS inside ${...}
                i += 2
                expr_depth = 1
                while i < len(line) and expr_depth > 0:
                    c2 = line[i]
                    if c2 == '\\':
                        i += 2
                        continue
                    if c2 == '"' or c2 == "'":
                        # Regular string
                        sc = c2
                        i += 1
                        while i < len(line):
                            if line[i] == '\\':
                                i += 2
                                continue
                            if line[i] == sc:
                                i += 1
                                break
                            i += 1
                        continue
                    if c2 == backtick:
                        # Nested template literal inside ${...}
                        i += 1
                        while i < len(line):
                            if line[i] == '\\':
                                i += 2
                                continue
                            if line[i] == backtick:
                                i += 1
                                break
                            if line[i] == '$' and i+1 < len(line) and line[i+1] == '{':
                                i += 2
                                expr_depth += 1
                                continue
                            i += 1
                        continue
                    if c2 == '{':
                        depth += 1
                    elif c2 == '}':
                        expr_depth -= 1
                        if expr_depth > 0:
                            depth -= 1
                    i += 1
                continue
        i += 1

    if depth != prev or in_tmpl:
        arrow = "++" if depth > prev else ("--" if depth < prev else "  ")
        snippet = line.strip()[:60]
        print("Line %4d: depth=%2d (was %2d) %s  %s" % (line_num, depth, prev, arrow, snippet))

print("\nFinal depth: %d" % depth)
if depth > 0:
    print("UNCLOSED BRACE - depth remaining: %d" % depth)
elif depth < 0:
    print("TOO MANY CLOSING BRACES - depth: %d" % depth)
else:
    print("All braces balanced!")
