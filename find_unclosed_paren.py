import urllib.request, sys

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

text = body.decode('utf-8', errors='replace')

def find_unclosed_parens(code):
    depth = 0
    i = 0
    stack = []  # (position, line_number)
    errors = []
    
    while i < len(code):
        c = code[i]
        ch = ord(c)
        
        if ch == 10 or ch == 13:
            i += 1; continue
        if ch <= 32:
            i += 1; continue
        
        # String double quote
        if c == '"':
            j = i + 1
            while j < len(code) and code[j] not in '"\n':
                if code[j] == '\\': j += 2
                else: j += 1
            i = j + 1; continue
        
        # String single quote
        if c == "'":
            j = i + 1
            while j < len(code) and code[j] not in "'\n":
                if code[j] == '\\': j += 2
                else: j += 1
            i = j + 1; continue
        
        # Template literal
        if c == '`':
            j = i + 1
            while j < len(code):
                if code[j] == '\\': j += 2; continue
                if code[j] == '`': break
                if code[j] == '$' and j + 1 < len(code) and code[j + 1] == '{':
                    j += 2; td = 1
                    while j < len(code) and td > 0:
                        if code[j] in '"\'':
                            q = code[j]; j += 1
                            while j < len(code) and code[j] != q:
                                if code[j] == '\\': j += 2
                                else: j += 1
                                j += 1
                            j += 1; continue
                        if code[j] == '{': td += 1
                        elif code[j] == '}': td -= 1
                        j += 1
                    continue
                j += 1
            i = j + 1; continue
        
        # Single line comment
        if c == '/' and i + 1 < len(code) and code[i+1] == '/':
            j = code.find('\n', i + 2)
            if j == -1: break
            i = j + 1; continue
        
        # Multi-line comment
        if c == '/' and i + 1 < len(code) and code[i+1] == '*':
            j = code.find('*/', i + 2)
            if j == -1:
                errors.append("Unclosed comment")
                break
            i = j + 2; continue
        
        if c == '(':
            ln = code[:i].count('\n') + 1
            stack.append((i, ln, '('))
            depth += 1
            i += 1; continue
        if c == ')':
            if depth > 0:
                depth -= 1
                stack.pop()
            else:
                ln = code[:i].count('\n') + 1
                snippet = code[max(0,i-40):i+30].replace('\n',' | ')
                errors.append("Extra ) at line " + str(ln) + ": " + snippet)
            i += 1; continue
        
        i += 1
    
    return depth, stack, errors

paren_depth, stack, errors = find_unclosed_parens(text)
print("Final paren depth:", paren_depth)
print("Errors:", errors)
print("Remaining (unclosed):", len(stack))
for pos, ln, typ in stack:
    snippet = text[max(0,pos-60):pos+30].replace('\n',' | ')
    print("  Line", ln, "pos", pos, ":", snippet[:120])
