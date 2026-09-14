import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8765/dashboard.js')
text = r.read().decode('utf-8')
lines = text.split('\n')

func_start = 1035  # 0-indexed
func_end = 1126    # inclusive

backtick = '\u0060'
depth = 0
in_str = False
str_char = None
in_tmpl = False
in_ml_comment = False

for line_num_0idx in range(func_start, func_end + 1):
    line = lines[line_num_0idx]
    file_line = line_num_0idx + 1
    prev_depth = depth
    net = 0
    i = 0

    while i < len(line):
        c = line[i]

        if in_ml_comment:
            if c == '*' and i+1 < len(line) and line[i+1] == '/':
                in_ml_comment = False
                i += 2
            else:
                i += 1
            continue

        if c == '\\' and (in_str or in_tmpl):
            i += 2
            continue

        if not in_str and not in_tmpl:
            if c == '/' and i+1 < len(line):
                if line[i+1] == '/':
                    break  # rest is comment
                elif line[i+1] == '*':
                    in_ml_comment = True
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
                net += 1
            elif c == '}':
                depth -= 1
                net -= 1
        elif in_str:
            if c == str_char:
                in_str = False
        elif in_tmpl:
            if c == backtick:
                in_tmpl = False
            elif c == '$' and i+1 < len(line) and line[i+1] == '{':
                # Enter template expression - scan for matching }
                i += 2
                brace_depth = 1
                while i < len(line) and brace_depth > 0:
                    if line[i] == '\\':
                        i += 2
                        continue
                    if line[i] == '{':
                        brace_depth += 1
                    elif line[i] == '}':
                        brace_depth -= 1
                    i += 1
                continue
        i += 1

    if net != 0 or in_tmpl or in_ml_comment:
        status = []
        if net != 0: status.append(f"net={net:+d}")
        if in_tmpl: status.append("in_tmpl=True")
        if in_ml_comment: status.append("in_ml_comment=True")
        print(f"Line {file_line}: depth={depth}, {', '.join(status)}")
        if abs(net) > 0:
            ctx = line.strip()[:80]
            print(f"  → {ctx!r}")

print(f"\nFinal depth: {depth}, in_tmpl={in_tmpl}, in_str={in_str}")
