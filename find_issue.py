import re

with open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/index.html', 'rb') as f:
    raw = f.read()

text = raw.decode('utf-8', errors='replace')

backtick = '\u0060'
script_start = text.index('\n<script>\n') + len('\n<script>\n')
script_end = text.rindex('</script>')

script_content = text[script_start:script_end]
print(f"Script content: {len(script_content)} chars")

# Scan through the script and find all template literal regions
# Then check if </script appears inside them
regions = []
in_template = False
template_start = 0
i = 0
while i < len(script_content):
    c = script_content[i]
    if c == backtick:
        if not in_template:
            in_template = True
            template_start = i
        else:
            in_template = False
            regions.append((template_start, i, 'closed'))
        i += 1
        continue
    i += 1

open_templates = [r for r in regions if r[2] == 'open']
print(f"Template literals: {len([r for r in regions if r[2]=='closed'])} closed, {len(open_templates)} open")

# Now find all occurrences of </script in the script content
for m in re.finditer('</scr', script_content):
    pos = m.start()
    # Check: is this inside a template literal?
    inside_template = False
    for ts, te, state in regions:
        if ts <= pos < te:
            inside_template = True
            break
    line_num = script_content[:pos].count('\n') + 1
    ctx = script_content[max(0,pos-40):pos+40]
    print(f"\n</scr at char {pos} (line {line_num}), inside_template={inside_template}")
    print(f"  Context: {repr(ctx)}")

# Also show the first 3 closed template literals
print("\nFirst 3 template literals:")
count = 0
for ts, te, state in regions:
    if state == 'closed' and count < 3:
        content_preview = script_content[ts+1:min(te,ts+80)]
        print(f"  [{ts}..{te}]: {repr(content_preview)}...")
        count += 1

# And show the first unclosed template
for ts, te, state in regions:
    if state == 'open':
        content_preview = script_content[ts+1:ts+100]
        print(f"\nFirst UNCLOSED template literal at char {ts}:")
        print(f"  Content start: {repr(content_preview)}...")
        line_num = script_content[:ts].count('\n') + 1
        print(f"  (starts at script line {line_num})")
        break
