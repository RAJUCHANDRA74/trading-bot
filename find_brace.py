import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
raw = r.read()
text = raw.decode('utf-8')

backtick = '\u0060'
i = 0
line = 1
depth = 0
brace_depth = 0
in_sl_comment = False
in_ml_comment = False
in_string = False
str_char = None
in_template = False
template_depth = 0
escaped = False
brace_stack = []  # (position, line) of opening braces
unmatched = []

while i < len(text):
    c = text[i]

    if c == '\n':
        line += 1
        in_sl_comment = False
    elif c == '\r':
        i += 1
        continue

    if escaped:
        escaped = False
        i += 1
        continue
    if c == '\\' and (in_string or in_template):
        escaped = True
        i += 1
        continue

    # Multi-line comment
    if in_ml_comment:
        if c == '*' and i+1 < len(text) and text[i+1] == '/':
            in_ml_comment = False
            i += 2
        else:
            i += 1
        continue

    # Single-line comment
    if in_sl_comment:
        i += 1
        continue

    # Not in comment or string
    if not in_string and not in_template:
        if c == '/' and i+1 < len(text):
            if text[i+1] == '/':
                in_sl_comment = True
                i += 2
                continue
            elif text[i+1] == '*':
                in_ml_comment = True
                i += 2
                continue

        if c == '"' or c == "'":
            in_string = True
            str_char = c
            i += 1
            continue
        elif c == backtick:
            in_template = True
            template_depth = 1
            i += 1
            continue
        elif c == '{':
            brace_depth += 1
            brace_stack.append((i, line))
            i += 1
            continue
        elif c == '}':
            brace_depth -= 1
            if brace_stack:
                brace_stack.pop()
            i += 1
            continue

    elif in_string:
        if c == str_char:
            in_string = False
        i += 1
        continue

    elif in_template:
        if c == backtick:
            in_template = False
            template_depth = 0
        elif c == '$' and i+1 < len(text) and text[i+1] == '{':
            template_depth += 1
        elif c == '}':
            template_depth -= 1
        i += 1
        continue

    i += 1

print(f"Final brace_depth: {brace_depth}")
print(f"Unmatched opening braces: {len(brace_stack)}")
if brace_stack:
    for pos, ln in brace_stack:
        ctx = text[max(0,pos-60):pos+100]
        print(f"\n  UNCLOSED {{ at line {ln}, char {pos}:")
        print(f"  Context: {ctx!r}")
else:
    print("All braces are balanced!")

# Also check: template literals
if in_template:
    print(f"\nUNCLOSED template literal (template_depth={template_depth})")
