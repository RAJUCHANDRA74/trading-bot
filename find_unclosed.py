import urllib.request, sys

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

text = body.decode('utf-8')
lines = text.split('\n')
print("Size: " + str(len(body)) + " bytes, " + str(len(lines)) + " lines")

depth = 0
max_depth = 0
i = 0
stack = []

while i < len(text):
    c = text[i]

    if c in '\r\n':
        i += 1; continue
    if c in ' \t':
        i += 1; continue

    if c == '"':
        j = i + 1
        while j < len(text) and text[j] not in '"\r\n':
            if text[j] == '\\': j += 2
            else: j += 1
        i = j + 1; continue

    if c == "'":
        j = i + 1
        while j < len(text) and text[j] not in "'\r\n":
            if text[j] == '\\': j += 2
            else: j += 1
        i = j + 1; continue

    if c == '`':
        j = i + 1
        while j < len(text):
            if text[j] == '\\': j += 2; continue
            if text[j] == '`': break
            if text[j] == '$' and j + 1 < len(text) and text[j + 1] == '{':
                j += 2; td = 1
                while j < len(text) and td > 0:
                    if text[j] in '"\'':
                        q = text[j]; j += 1
                        while j < len(text):
                            if text[j] == '\\': j += 2; continue
                            if text[j] == q: break
                            j += 1
                        j += 1; continue
                    if text[j] == '{': td += 1
                    elif text[j] == '}': td -= 1
                    j += 1
                continue
            j += 1
        i = j + 1; continue

    if c == '/' and i + 1 < len(text):
        if text[i+1] == '/':
            j = text.find('\n', i+2)
            if j == -1: break
            i = j + 1; continue
        if text[i+1] == '*':
            j = text.find('*/', i+2)
            if j == -1:
                print("Unclosed comment"); sys.exit(1)
            i = j + 2; continue

    if c == '{': 
        depth += 1
        max_depth = max(max_depth, depth)
        ln = text[:i].count('\n') + 1
        stack.append(ln)
        i += 1; continue
    if c == '}':
        ln = text[:i].count('\n') + 1
        if depth > 0:
            depth -= 1
            stack.pop()
        else:
            print("Extra } at line " + str(ln) + ": " + lines[ln-1][:60])
        i += 1; continue

    i += 1

print("Final depth: " + str(depth) + " | Max: " + str(max_depth))
if depth > 0:
    print("Unclosed braces (" + str(depth) + "):")
    for ln in stack:
        line_content = lines[ln-1] if ln <= len(lines) else '?'
        print("  Line " + str(ln) + ": " + line_content[:100])
else:
    print("All balanced!")
