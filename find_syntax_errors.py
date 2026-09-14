import re, sys

with open('dashboard/dashboard.js', 'r', encoding='utf-8') as f:
    code = f.read()

# Tokenize and check for syntax issues
tokens = []
i = 0
line = 1
col = 0

while i < len(code):
    c = code[i]
    if c == '\n':
        line += 1
        col = 0
        i += 1
        continue

    # Skip whitespace
    if c in ' \t\r':
        col += 1
        i += 1
        continue

    # Single-line comment
    if c == '/' and i + 1 < len(code) and code[i+1] == '/':
        end = code.find('\n', i)
        if end == -1: end = len(code)
        i = end
        continue

    # Multi-line comment
    if c == '/' and i + 1 < len(code) and code[i+1] == '*':
        end = code.find('*/', i + 2)
        if end == -1:
            print("ERROR: Unclosed multi-line comment starting at line", line)
            sys.exit(1)
        line += code[i:end+2].count('\n')
        i = end + 2
        continue

    # Template literal
    if c == '`':
        # Find matching backtick (skipping ${} and strings inside)
        i += 1
        depth = 1
        in_str_d = False
        in_str_s = False
        in_expr = 0
        while i < len(code) and depth > 0:
            ch = code[i]
            if in_str_d:
                if ch == '"': in_str_d = False
                i += 1; continue
            if in_str_s:
                if ch == "'": in_str_s = False
                i += 1; continue
            if ch == '"': in_str_d = True; i += 1; continue
            if ch == "'": in_str_s = True; i += 1; continue
            if ch == '`':
                depth -= 1
                if depth == 0: break
            i += 1
        if depth > 0:
            print("ERROR: Unclosed template literal at line", line)
            sys.exit(1)
        i += 1
        continue

    # String
    if c in '"\'':
        quote = c
        i += 1
        while i < len(code):
            if code[i] == '\\': i += 2; continue
            if code[i] == quote: break
            if code[i] == '\n': break  # unclosed string
            i += 1
        i += 1
        continue

    # Number
    if c.isdigit() or (c == '.' and i + 1 < len(code) and code[i+1].isdigit()):
        while i < len(code) and (code[i].isalnum() or code[i] in '._'):
            i += 1
        continue

    # Identifier/keyword
    if c.isalpha() or c == '_' or c == '$':
        while i < len(code) and (code[i].isalnum() or code[i] in '_$'):
            i += 1
        continue

    # Operators and punctuation
    if c in '(){}[];,:?=>!+-*/%&=|^~<>.':
        tokens.append((c, line))
        col += 1
        i += 1
        continue

    # Unknown character
    print(f"WARNING: Unknown char '{c}' (ord={ord(c)}) at line {line}")
    i += 1

# Check for mismatched parentheses/brackets
paren_depth = 0
bracket_depth = 0
brace_depth = 0
paren_stack = []
bracket_stack = []
brace_stack = []

# We already tracked braces in template literals; now just check regular code
i = 0
while i < len(code):
    c = code[i]

    # Skip comments
    if c == '/' and i + 1 < len(code) and code[i+1] == '/':
        end = code.find('\n', i)
        if end == -1: end = len(code)
        i = end; continue
    if c == '/' and i + 1 < len(code) and code[i+1] == '*':
        end = code.find('*/', i + 2)
        if end == -1: break
        i = end + 2; continue

    # Skip strings and template literals
    if c in '"\'':
        quote = c; i += 1
        while i < len(code):
            if code[i] == '\\': i += 2; continue
            if code[i] == quote: break
            if code[i] == '\n': break
            i += 1
        i += 1; continue
    if c == '`':
        i += 1; continue

    # Track parens/brackets/braces
    if c == '(':
        paren_stack.append((line, ')'))
        paren_depth += 1
    elif c == ')':
        if paren_stack and paren_stack[-1][1] == ')':
            paren_stack.pop()
        else:
            print(f"ERROR: Unexpected ')' at line {line} (stack: {paren_stack})")
        paren_depth -= 1
        if paren_depth < 0:
            print(f"ERROR: Unmatched ')' at line {line}")
            paren_depth = 0
    elif c == '[':
        bracket_stack.append((line, ']'))
        bracket_depth += 1
    elif c == ']':
        if bracket_stack and bracket_stack[-1][1] == ']':
            bracket_stack.pop()
        else:
            print(f"ERROR: Unexpected ']' at line {line}")
        bracket_depth -= 1
    elif c == '{':
        brace_stack.append((line, '}'))
        brace_depth += 1
    elif c == '}':
        if brace_stack and brace_stack[-1][1] == '}':
            brace_stack.pop()
        else:
            print(f"ERROR: Unexpected '}}' at line {line} (stack: {brace_stack})")
        brace_depth -= 1
        if brace_depth < 0:
            print(f"ERROR: Unmatched '}}' at line {line}")
            brace_depth = 0

    i += 1

print(f"Lines: {line}")
print(f"Paren depth remaining: {paren_depth}, stack: {paren_stack}")
print(f"Bracket depth remaining: {bracket_depth}, stack: {bracket_stack}")
print(f"Brace depth remaining: {brace_depth}, stack: {brace_stack}")

if paren_depth != 0 or bracket_depth != 0 or brace_depth != 0:
    print("ERROR: Mismatched brackets!")
    sys.exit(1)
else:
    print("All brackets balanced!")
