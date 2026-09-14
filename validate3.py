with open('dashboard/dashboard.js', 'r', encoding='utf-8') as f:
    code = f.read()

# Check connectWS
start = code.find('function connectWS(){')
end = code.find('\n/* ', start + 1)
region = code[start:end]
print("connectWS region length:", len(region))

depth = 0
in_str = False
str_char = None
in_ml_comment = False
in_sl_comment = False
in_template = False
i = 0

while i < len(region):
    c = region[i]

    if not in_str and not in_sl_comment and i + 1 < len(region):
        if c == '/' and region[i + 1] == '*':
            in_ml_comment = True
            i += 2
            continue
    if in_ml_comment:
        if c == '*' and i + 1 < len(region) and region[i + 1] == '/':
            in_ml_comment = False
        i += 1
        continue

    if not in_str and c == '/' and i + 1 < len(region) and region[i + 1] == '/':
        in_sl_comment = True
        i += 2
        continue
    if in_sl_comment:
        if c == '\n':
            in_sl_comment = False
        i += 1
        continue

    if c == '`' and not in_str:
        in_template = not in_template
        i += 1
        continue
    if in_template:
        i += 1
        continue

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

    if c == '$' and i + 1 < len(region) and region[i + 1] == '{':
        i += 2
        expr_depth = 1
        in_expr_str = False
        expr_str_char = None
        while i < len(region) and expr_depth > 0:
            ec = region[i]
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
        continue

    if c == '{':
        depth += 1
        snippet = region[max(0, i - 40):i + 1].replace('\n', ' ')
        print("OPEN { (d=" + str(depth) + ") at " + str(i) + ": ..." + snippet[-60:])
    elif c == '}':
        snippet = region[max(0, i - 40):i + 1].replace('\n', ' ')
        print("CLOSE } (d=" + str(depth) + ") at " + str(i) + ": ..." + snippet[-60:])
        depth -= 1
    i += 1

print("\nFinal depth:", depth)
if depth == 0:
    print("OK: connectWS is balanced!")
else:
    print("ERROR: unclosed braces in connectWS!")
