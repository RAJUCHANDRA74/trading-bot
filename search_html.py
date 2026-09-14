import urllib.request

url = "http://127.0.0.1:8765/"
with urllib.request.urlopen(url, timeout=5) as resp:
    html = resp.read().decode('utf-8')

print("HTML size:", len(html))

# Find all script blocks
import re
scripts = list(re.finditer(r'<script[^>]*>', html))
print("Script blocks found:", len(scripts))
for m in scripts:
    start = m.start()
    end_tag = html.find('</script>', start)
    end = end_tag + 9 if end_tag != -1 else min(start + 500, len(html))
    content = html[m.start():end]
    print("\n--- Script at pos", start, "---")
    print("Tag:", content[:100])
    if '</script>' in content:
        # Has content (inline or partial)
        inner_start = m.end()
        inner = html[inner_start:end_tag] if end_tag != -1 else html[inner_start:]
        print("Inline content length:", len(inner))
        if inner.strip():
            print("First 200 chars of inline:", inner[:200])
    else:
        src = re.search(r'src=["\']([^"\']+)["\']', m.group())
        print("External src:", src.group(1) if src else "none")
