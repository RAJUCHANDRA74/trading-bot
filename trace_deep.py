import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
text = r.read().decode('utf-8')
lines = text.split('\n')

func_start = 1035
func_end = 1126
backtick = '\u0060'

# Full state machine tracking depth EXACTLY as Chrome does
depth = 0
in_str = False
str_char = None
in_sl = False
in_ml = False
in_tmpl = False
escaped = False

for line_num_0idx in range(func_start, func_end + 1):
    line = lines[line_num_0idx]
    file_line = line_num_0idx + 1
    prev = depth

    i = 0
    while i < len(line):
        c = line[i]

        if c == '\n':
            in_sl = False
            i += 1
            continue

        if escaped:
            escaped = False
            i += 1
            continue

        if c == '\\' and (in_str or in_tmpl):
            escaped = True
            i += 1
            continue

        # Multi-line comment
        if in_ml:
            if c == '*' and i+1 < len(line) and line[i+1] == '/':
                in_ml = False
            i += 1
            continue

        # Not in comment/string
        if not in_str and not in_tmpl:
            if c == '/' and i+1 < len(line):
                if line[i+1] == '/':
                    in_sl = True
                    i += 2
                    continue
                elif line[i+1] == '*':
                    in_ml = True
                    i += 2
                    continue

            if c == '"' or c == "'":
                in_str = True
                str_char = c
                i += 1
                continue
            elif c == backtick:
                in_tmpl = True
                i += 1
                continue
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
        elif in_str:
            if c == str_char:
                in_str = False
        elif in_tmpl:
            # In template literal - check for ${...} expressions
            if c == backtick:
                in_tmpl = False
                i += 1
                continue
            if c == '$' and i+1 < len(line) and line[i+1] == '{':
                # Enter template expression - parse JS inside ${...}
                i += 2  # skip ${
                expr_depth = 1
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
                        if expr_depth == 0:
                            pass  # expression closed, continue in template
                        else:
                            depth -= 1
                    i += 1
                continue
        i += 1

    if depth != prev:
        print(f"Line {file_line}: depth {prev} -> {depth} | {line.strip()[:80]}")
    elif in_tmpl or in_ml:
        print(f"Line {file_line}: still in_tmpl={in_tmpl} in_ml={in_ml} | {line.strip()[:60]}")

print(f"\nFinal depth: {depth}")
if depth > 0:
    print("UNCLOSED BRACE!")
