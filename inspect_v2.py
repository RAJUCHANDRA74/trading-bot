import urllib.request

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

text = body.decode('utf-8')
lines = text.split('\n')

print("File size:", len(body), "bytes,", len(lines), "lines")

# Check first 10 lines for any issues
print("\n=== First 10 lines ===")
for i in range(min(10, len(lines))):
    line = lines[i]
    print("Line", i+1, "(len=", len(line), "):", repr(line[:80]))

# Check first 10 bytes
print("\nFirst 10 bytes (hex):", body[:10].hex())

# Run the comprehensive brace check
print("\n=== Running brace check ===")
import sys

depth = 0
i = 0
errors = []
max_depth = 0

while i < len(text):
    c = text[i]

    # Newlines
    if c in '\r\n':
        i += 1
        continue

    # Whitespace
    if c in ' \t':
        i += 1
        continue

    # String double quote
    if c == '"':
        j = i + 1
        while j < len(text):
            if text[j] == '\\':
                j += 2
                continue
            if text[j] == '"':
                break
            j += 1
        i = j + 1
        continue

    # String single quote
    if c == "'":
        j = i + 1
        while j < len(text):
            if text[j] == '\\':
                j += 2
                continue
            if text[j] == "'":
                break
            j += 1
        i = j + 1
        continue

    # Template literal
    if c == '`':
        j = i + 1
        while j < len(text):
            if text[j] == '\\':
                j += 2
                continue
            if text[j] == '`':
                break
            # ${} in template
            if text[j] == '$' and j + 1 < len(text) and text[j + 1] == '{':
                j += 2
                tl_depth = 1
                while j < len(text) and tl_depth > 0:
                    if text[j] in '"\'':
                        q = text[j]
                        j += 1
                        while j < len(text):
                            if text[j] == '\\':
                                j += 2
                                continue
                            if text[j] == q:
                                break
                            j += 1
                        j += 1
                        continue
                    if text[j] == '{':
                        tl_depth += 1
                    elif text[j] == '}':
                        tl_depth -= 1
                    j += 1
                continue
            j += 1
        i = j + 1
        continue

    # Single line comment
    if c == '/' and i + 1 < len(text) and text[i + 1] == '/':
        j = text.find('\n', i + 2)
        if j == -1:
            break
        i = j + 1
        continue

    # Multi-line comment
    if c == '/' and i + 1 < len(text) and text[i + 1] == '*':
        j = text.find('*/', i + 2)
        if j == -1:
            errors.append("Unclosed multi-line comment starting at char " + str(i))
            break
        i = j + 2
        continue

    # Braces
    if c == '{':
        depth += 1
        max_depth = max(max_depth, depth)
        i += 1
        continue

    if c == '}':
        if depth == 0:
            line_num = text[:i].count('\n') + 1
            errors.append("Extra } at line " + str(line_num) + ": ..." + text[max(0,i-50):i+20] + "...")
        depth -= 1
        i += 1
        continue

    i += 1

print("Final brace depth:", depth)
print("Max nesting depth:", max_depth)
if errors:
    print("ERRORS:")
    for e in errors:
        print(" ", e)
else:
    print("All braces balanced!")
