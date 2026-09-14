import urllib.request, sys

# Fetch the served dashboard.js raw
url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

print("Served size:", len(body), "bytes")

# Check for BOM
print("Starts with BOM:", body[:3] == b'\xef\xbb\xbf')

# Check first 10 bytes
print("First 10 bytes:", ' '.join('%02X' % b for b in body[:10]))

# Decode and check lines
text = body.decode('utf-8', errors='replace')
lines = text.split('\n')
print("Lines:", len(lines))

# Save a copy
with open('live_dashboard.js', 'wb') as f:
    f.write(body)

# Now do a BRUTE-FORCE check: every single '(' must have a matching ')'
# Count parens ignoring strings, comments, template literals

def count_parens_ignore_context(code):
    depth = 0
    i = 0
    max_depth = 0
    errors = []
    
    while i < len(code):
        c = code[i]
        ch = ord(c)
        
        # Newline
        if ch == 10 or ch == 13:
            i += 1; continue
        
        # Skip space/tab
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
                errors.append("Unclosed multi-line comment at char " + str(i))
                break
            i = j + 2; continue
        
        # Parens - track them
        if c == '(':
            depth += 1
            max_depth = max(max_depth, depth)
            i += 1; continue
        if c == ')':
            if depth == 0:
                ln = code[:i].count('\n') + 1
                snippet = code[max(0,i-50):i+30].replace('\n',' | ')
                errors.append("Extra ')' at line " + str(ln) + ": " + snippet)
            depth -= 1
            i += 1; continue
        
        i += 1
    
    return depth, max_depth, errors

paren_depth, max_paren, errors = count_parens_ignore_context(text)
print("Paren depth:", paren_depth, "| Max paren:", max_paren)
if errors:
    print("ERRORS:")
    for e in errors:
        print(" ", e)
    sys.exit(1)
else:
    print("All parens OK!")
