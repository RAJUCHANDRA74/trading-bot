"""Find the exact unclosed brace by tracking where it starts."""
data = open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/index.html', 'rb').read()
last_script_start = data.rfind(b'<script>')
last_script_end = data.rfind(b'</script>')
js_bytes = data[last_script_start + 8:last_script_end]
js = js_bytes.decode('utf-8', errors='replace')

depth = 0
in_str = False
str_char = None
in_tpl = False
in_comment = False
in_ml_comment = False

for i, ch in enumerate(js):
    if in_ml_comment:
        if ch == '*' and i + 1 < len(js) and js[i+1] == '/':
            in_ml_comment = False
        continue
    
    if in_comment:
        if ch == '\n':
            in_comment = False
        continue
    
    if in_str:
        if ch == '\\' and i + 1 < len(js):
            i += 1  # skip escaped char
        elif ch == str_char:
            in_str = False
    elif in_tpl:
        if ch == '\\' and i + 1 < len(js):
            i += 1
        elif ch == '`':
            in_tpl = False
        elif ch == '$' and i + 1 < len(js) and js[i+1] == '{':
            # Template literal interpolation - SKIP the entire content
            j = i + 2
            tpl_depth = 1
            while j < len(js) and tpl_depth > 0:
                c = js[j]
                if c == '\\' and j + 1 < len(js):
                    j += 2
                    continue
                elif c == '`':
                    # End of outer template literal
                    break
                elif c == '{':
                    tpl_depth += 1
                elif c == '}':
                    tpl_depth -= 1
                j += 1
            i = j  # will be incremented by for loop
            continue
    else:
        if js[i:i+2] == '//':
            in_comment = True
            i += 1
            continue
        elif js[i:i+2] == '/*':
            in_ml_comment = True
            i += 1
            continue
        elif ch in '"\'':
            in_str = True
            str_char = ch
        elif ch == '`':
            in_tpl = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1

print(f'Final depth: {depth}', flush=True)

if depth > 0:
    # Scan again to find the last OPENING brace position
    depth = 0
    in_str = False
    str_char = None
    in_tpl = False
    in_comment = False
    in_ml_comment = False
    
    last_open_pos = None
    
    for i, ch in enumerate(js):
        if in_ml_comment:
            if ch == '*' and i + 1 < len(js) and js[i+1] == '/':
                in_ml_comment = False
            continue
        
        if in_comment:
            if ch == '\n':
                in_comment = False
            continue
        
        if in_str:
            if ch == '\\' and i + 1 < len(js):
                i += 1
            elif ch == str_char:
                in_str = False
        elif in_tpl:
            if ch == '\\' and i + 1 < len(js):
                i += 1
            elif ch == '`':
                in_tpl = False
            elif ch == '$' and i + 1 < len(js) and js[i+1] == '{':
                j = i + 2
                tpl_depth = 1
                while j < len(js) and tpl_depth > 0:
                    c = js[j]
                    if c == '\\' and j + 1 < len(js):
                        j += 2
                        continue
                    elif c == '`':
                        break
                    elif c == '{':
                        tpl_depth += 1
                    elif c == '}':
                        tpl_depth -= 1
                    j += 1
                i = j
                continue
        else:
            if js[i:i+2] == '//':
                in_comment = True
                i += 1
                continue
            elif js[i:i+2] == '/*':
                in_ml_comment = True
                i += 1
                continue
            elif ch in '"\'':
                in_str = True
                str_char = ch
            elif ch == '`':
                in_tpl = True
            elif ch == '{':
                depth += 1
                last_open_pos = i
            elif ch == '}':
                depth -= 1
        
        # Stop once we've found all unclosed braces
        if i > 100000:  # safety limit
            break
    
    print(f'Last opening brace pos: {last_open_pos}', flush=True)
    if last_open_pos is not None:
        lines = js.split('\n')
        char_count = 0
        for li, line in enumerate(lines):
            if char_count + len(line) + 1 > last_open_pos:
                print(f'At HTML line: {li+1}', flush=True)
                print(f'Line: {repr(line[:100])}', flush=True)
                print(f'Context: {repr(js[max(0,last_open_pos-100):last_open_pos+100])}', flush=True)
                break
            char_count += len(line) + 1
