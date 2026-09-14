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
in_tmpl = False    # am I inside any template literal right now?
nested_tmpl = 0    # how many nested backticks inside ${...} are currently open?
in_expr = False    # am I inside a ${...} right now?
expr_depth = 0     # how many ${...} are open?

print("=== CORRECT CROSS-LINE TEMPLATE TRACE ===")
for ln_idx in range(func_start, func_end + 1):
    line = lines[ln_idx]
    line_num = ln_idx + 1
    prev = depth
    i = 0

    while i < len(line):
        c = line[i]

        if c == '\\':
            i += 2
            continue

        if c == '/' and i+1 < len(line) and line[i+1] == '*':
            end = line.find('*/', i+2)
            if end >= 0:
                i = end + 2
            else:
                break
            continue

        if c == '/' and i+1 < len(line) and line[i+1] == '/':
            break

        if not in_tmpl:
            # Outside any template literal
            if c == backtick:
                in_tmpl = True
                nested_tmpl = 0
                i += 1
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
        else:
            # Inside a template literal
            if c == backtick:
                # Closing backtick
                if nested_tmpl > 0:
                    # Closing a nested template inside ${...}
                    nested_tmpl -= 1
                    # in_tmpl stays True, in_expr stays True
                elif in_expr and expr_depth > 0:
                    # Closing the CURRENT template (opened from ${...})
                    # Outer template might still be open from an earlier ${...}
                    in_tmpl = in_expr  # if still in expression, template continues
                    in_expr = False
                    expr_depth = 0
                else:
                    # No active expression, this closes the template
                    in_tmpl = False
                    nested_tmpl = 0
                i += 1
                continue

            if c == '$' and i+1 < len(line) and line[i+1] == '{':
                # Enter ${...} expression
                i += 2
                in_expr = True
                expr_depth += 1
                while i < len(line) and expr_depth > 0:
                    c2 = line[i]
                    if c2 == '\\':
                        i += 2
                        continue
                    if c2 == '"' or c2 == "'":
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
                        # Nested template literal
                        in_tmpl = True
                        nested_tmpl += 1
                        i += 1
                        continue
                    if c2 == '{':
                        depth += 1
                    elif c2 == '}':
                        expr_depth -= 1
                        if expr_depth > 0:
                            depth -= 1
                        if expr_depth == 0:
                            in_expr = False
                    i += 1
                continue
        i += 1

    marker = ""
    if depth != prev:
        marker = " ***"
    if in_tmpl:
        marker += " in_tmpl"
    if in_expr:
        marker += " in_expr"
    snippet = line.strip()[:60]
    print("L%4d: d=%2d(p=%2d)%s  %s" % (line_num, depth, prev, marker, snippet))

print("\nFinal depth: %d, in_tmpl=%s, nested=%d, in_expr=%s, expr_depth=%d" % (
    depth, in_tmpl, nested_tmpl, in_expr, expr_depth))
if depth > 0:
    print("UNCLOSED BRACES!")
