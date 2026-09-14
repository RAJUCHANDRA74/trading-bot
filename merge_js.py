import re

html_path = r'C:\Users\Rajkumar\.minimax-agent\projects\trading-bot\dashboard\index.html'
js_path = r'C:\Users\Rajkumar\.minimax-agent\projects\trading-bot\dashboard\dashboard.js'

with open(html_path, 'r', encoding='utf-8') as f:
    html_content = f.read()

with open(js_path, 'r', encoding='utf-8') as f:
    js_content = f.read()

# Fix: escape </script> inside JS to prevent HTML parser from closing the script block early
# Use </scr" + "ipt> which prevents the HTML parser from seeing it
js_content_escaped = js_content.replace('</script>', '</scr" + "ipt>')

# Find and replace the script tag
# The current index.html has the already-replaced version, so check for inline script
# If the file already has inline JS, we need to re-read from the split files
# First check if it was already merged (has inline <script> but no src=)
has_inline = '<script>\n' in html_content
has_src = 'script src=' in html_content

if has_src:
    # Replace external script tag with inline
    pattern = r'<script\s+src="dashboard\.js"\s*>\s*</script>'
    replacement = f'<script>\n{js_content_escaped}\n</script>'
    new_html = re.sub(pattern, replacement, html_content)
elif has_inline:
    # Already merged, need to update the inline JS
    # Find the inline script block and replace it
    start = html_content.find('<script>\n')
    end = html_content.rfind('</script>')
    if start != -1 and end != -1:
        new_html = html_content[:start] + f'<script>\n{js_content_escaped}\n</script>' + html_content[end + len('</script>'):]
    else:
        print("ERROR: Could not find inline script block to replace")
        exit(1)
else:
    print("ERROR: No script tag found!")
    exit(1)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(new_html)

print(f"Done! Merged file: {len(new_html):,} bytes")
print(f"Original JS: {len(js_content):,} bytes")
# Verify no double-close
if '</script></script>' in new_html:
    print("WARNING: Double </script> found!")
else:
    print("OK: No double </script>")
