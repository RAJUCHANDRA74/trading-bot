"""Extract raw JS bytes and check strings."""
data = open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/index.html', 'rb').read()
last_script_start = data.rfind(b'<script>')
last_script_end = data.rfind(b'</script>')
js_bytes = data[last_script_start + 8:last_script_end]

print(f'JS bytes: {len(js_bytes)}', flush=True)
print(f'JS ends with: {repr(js_bytes[-20:])}', flush=True)

# Try to decode and check for decode errors
try:
    js = js_bytes.decode('utf-8')
    print('UTF-8 decode: OK', flush=True)
except UnicodeDecodeError as e:
    print(f'UTF-8 ERROR at {e.start}: {e.reason}', flush=True)

# Write JS to a separate file for inspection
with open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/script.js', 'wb') as f:
    f.write(js_bytes)
print('JS written to dashboard/script.js', flush=True)
