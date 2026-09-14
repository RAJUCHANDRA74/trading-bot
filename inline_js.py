html_path = r'C:\Users\Rajkumar\.minimax-agent\projects\trading-bot\dashboard\index.html'
js_path = r'C:\Users\Rajkumar\.minimax-agent\projects\trading-bot\dashboard\dashboard.js'

with open(html_path, 'rb') as f:
    html = f.read()
with open(js_path, 'rb') as f:
    js = f.read()

html = html.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
js = js.replace(b'\r\n', b'\n').replace(b'\r', b'\n')

# Replace </script> with </scr + "ipt"> — HTML parser never sees </script>
js_escaped = js.replace(b'</script>', b'</scr' + b' + "ipt">')

old_tag = b'<script src="dashboard.js"></script>'
if old_tag not in html:
    print('ERROR: tag not found')
    exit(1)

new_html = html.replace(old_tag, b'<script>\n' + js_escaped + b'\n</script>')

closes = new_html.count(b'</script>')
print('HTML:', len(new_html), 'bytes, </script>:', closes)
print('Has concatenation:', b'</scr' in new_html)

with open(html_path, 'wb') as f:
    f.write(new_html)
print('Written! Ends:', repr(new_html[-60:]))
