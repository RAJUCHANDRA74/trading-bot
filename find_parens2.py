import urllib.request

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

text = body.decode('utf-8')
lines = text.split('\n')

print("File: " + str(len(body)) + " bytes, " + str(len(lines)) + " lines")

# Search for patterns that cause "Unexpected token ')'"
# Pattern: "== )" or "=== )" (comparison missing right operand)
import re

# Pattern 1: ==) or ===) 
matches = list(re.finditer(r'={2,3}\s*\)', text))
print("\n1. ==) or ===) patterns: " + str(len(matches)))
for m in matches[:5]:
    ln = text[:m.start()].count('\n') + 1
    snippet = text[max(0,m.start()-40):m.end()+40].replace('\n',' | ')
    print("  Line " + str(ln) + ": " + snippet[:120])

# Pattern 2: ) followed by ) (double close paren without comma)
# Look for patterns like "))" that aren't "}})" or "()"
matches2 = list(re.finditer(r'(?<![<>!=(])($\s*\)){2,}', text))
print("\n2. Double )) patterns: " + str(len(matches2)))
for m in matches2[:5]:
    ln = text[:m.start()].count('\n') + 1
    snippet = text[max(0,m.start()-40):m.end()+40].replace('\n',' | ')
    print("  Line " + str(ln) + ": " + snippet[:120])

# Pattern 3: Look for "=> )" (arrow function returning nothing)
matches3 = list(re.finditer(r'=>\s*\)', text))
print("\n3. =>) patterns: " + str(len(matches3)))
for m in matches3[:5]:
    ln = text[:m.start()].count('\n') + 1
    snippet = text[max(0,m.start()-40):m.end()+40].replace('\n',' | ')
    print("  Line " + str(ln) + ": " + snippet[:120])

# Pattern 4: Check lines that are JUST ")" (bare close paren)
print("\n4. Lines that are just ')':")
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == ')':
        print("  Line " + str(i+1) + ": '" + stripped + "'")

# Pattern 5: Check for lines ending with ")" that shouldn't
print("\n5. Lines ending with suspicious ')'")
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.endswith(')') and not any(x in stripped for x in ['forEach','=>','.map(','.filter(','.reduce(','join(',.some(','.every(','.find(','.findIndex(']):
        # It's a line ending with ) that's NOT inside a callback
        # Check if it's a suspicious pattern
        if stripped in [')', '})', '}) }', '})};']:
            print("  Line " + str(i+1) + ": " + stripped)

# Pattern 6: Check the first 20 lines carefully
print("\n6. First 20 lines:")
for i in range(min(20, len(lines))):
    line = lines[i]
    clean = line.replace(chr(0x20b9),'Rs').replace(chr(0x25cf),'*')
    print("  " + str(i+1) + ": " + repr(clean[:100]))
