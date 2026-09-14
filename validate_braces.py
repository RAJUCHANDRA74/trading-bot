import sys

with open('dashboard/dashboard.js', 'r', encoding='utf-8') as f:
    code = f.read()

depth = 0
max_depth = 0
i = 0
in_str = False
str_char = None
in_ml_comment = False
in_sl_comment = False
in_template = False
open_positions = []

while i < len(code):
    c = code[i]

    # Multi-line comment
    if not in_str and not in_sl_comment and i + 1 < len(code):
        if c == '/' and code[i + 1] == '*':
            in_ml_comment = True
            i += 2
            continue
    if in_ml_comment:
        if c == '*' and i + 1 < len(code) and code[i + 1] == '/':
            in_ml_comment = False
            i += 2
        else:
            i += 1
        continue

    # Single-line comment
    if not in_str and c == '/' and i + 1 < len(code) and code[i + 1] == '/':
        in_sl_comment = True
        i += 2
        continue
    if in_sl_comment:
        if c == '\n':
            in_sl_comment = False
        i += 1
        continue

    # Template literal
    if c == '`' and not in_str:
        in_template = not in_template
        i += 1
        continue
    if in_template:
        i += 1
        continue

    # String
    if c in ('"', "'") and not in_str:
        in_str = True
        str_char = c
        i += 1
        continue
    if in_str:
        if c == str_char:
            in_str = False
        i += 1
        continue

    # Skip ${ in template (template is handled above, but ${} can nest)
    if c == '$' and i + 1 < len(code) and code[i + 1] == '{':
        i += 2
        expr_depth = 1
        in_expr_str = False
        expr_str_char = None
        while i < len(code) and expr_depth > 0:
            ec = code[i]
            if in_expr_str:
                if ec == expr_str_char:
                    in_expr_str = False
                i += 1
                continue
            if ec in ('"', "'"):
                in_expr_str = True
                expr_str_char = ec
                i += 1
                continue
            if ec == '{':
                expr_depth += 1
            elif ec == '}':
                expr_depth -= 1
            i += 1
        # Don't increment i again — the while loop handles it
        continue

    if c == '{':
        depth += 1
        max_depth = max(max_depth, depth)
        open_positions.append(i)
        snippet = code[max(0, i - 30):i + 1].replace('\n', '\\n')
        print("  OPEN { at pos " + str(i) + " (depth=" + str(depth) + "): ..." + snippet)
    elif c == '}':
        if depth == 0:
            snippet2 = code[max(0, i - 30):i + 1].replace('\n', '\\n')
            print("  UNEXPECTED } at pos " + str(i) + ": ..." + snippet2)
        depth -= 1
        if open_positions:
            open_positions.pop()

    i += 1

print("\nFinal depth: " + str(depth) + " (should be 0)")
print("Max nesting depth: " + str(max_depth))
if depth > 0:
    print("Still open positions: " + str(open_positions))
    for pos in open_positions:
        snippet = code[max(0, pos - 40):pos + 1].replace('\n', '\\n')
        print("  Pos " + str(pos) + ": ..." + snippet)
    print("\nERROR: Unclosed braces!")
    sys.exit(1)
else:
    print("OK: All braces balanced")
