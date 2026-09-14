import re

with open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/index.html', 'rb') as f:
    raw = f.read()

text = raw.decode('utf-8', errors='replace')
backtick = '\u0060'

# Find all </script in the raw text (between <script> and </script>)
script_open = text.index('<script>') + len('<script>')
script_close = text.rindex('</script>')
script_text = text[script_open:script_close]

print(f"Searching {len(script_text)} chars of script content")
print(f"Total </scr in script: {script_text.count('</scr')}")

# Find all </scr positions
for m in re.finditer('</scr', script_text):
    pos = m.start()
    ctx = script_text[max(0,pos-60):pos+60]
    line_num = script_text[:pos].count('\n') + 1
    print(f"\n</scr at line {line_num}, char {pos}:")
    print(f"  {repr(ctx)}")

# Also check for <script> in script (would be inside a string)
print(f"\nTotal <script in script: {script_text.count('<script>')}")
print(f"Total `</script` in script: {script_text.count('<script`')}")

# The real question: is there any literal </script> in a JS string?
# We need to check if any string literal contains </script
print("\n=== Checking strings for </script> ===")

def extract_strings_and_check(content):
    """Extract all string content and check for </script"""
    i = 0
    in_str = False
    str_char = None
    escaped = False
    
    while i < len(content):
        c = content[i]
        
        if escaped:
            escaped = False
            i += 1
            continue
        
        if c == '\\':
            escaped = True
            i += 1
            continue
        
        if not in_str:
            if c in ('"', "'"):
                in_str = True
                str_char = c
                str_start = i
            elif c == backtick:
                # Template literal
                str_start = i
                j = i + 1
                while j < len(content):
                    if content[j] == '\\':
                        j += 2
                        continue
                    if content[j] == '`':
                        break
                    if content[j] == '$' and j+1 < len(content) and content[j+1] == '{':
                        # Find matching }
                        depth = 1
                        j += 2
                        while j < len(content) and depth > 0:
                            if content[j] == '{':
                                depth += 1
                            elif content[j] == '}':
                                depth -= 1
                            j += 1
                        continue
                    j += 1
                str_content = content[str_start+1:j]
                if '</scr' in str_content:
                    line_num = content[:str_start].count('\n') + 1
                    print(f"  TEMPLATE LIT at line {line_num} contains </scr: {repr(str_content[:100])}")
                i = j + 1
                continue
        else:
            if c == str_char:
                in_str = False
        i += 1

extract_strings_and_check(script_text)
