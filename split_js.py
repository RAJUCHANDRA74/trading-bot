data = open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/index.html', 'rb').read()
last_script_start = data.rfind(b'<script>')
last_script_end = data.rfind(b'</script>')
js_bytes = data[last_script_start + 8:last_script_end]

# Write JS to separate file
with open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/dashboard.js', 'wb') as f:
    f.write(js_bytes)
print('JS written:', len(js_bytes), 'bytes')

# Create new HTML with script src reference
html_start = data[:last_script_start]
html_end = data[last_script_end + 9:]  # after </script>

# Build the replacement
replacement = b'<script src="dashboard.js"></script>'
new_html = html_start + replacement + html_end

with open('C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/index.html', 'wb') as f:
    f.write(new_html)
print('New HTML written:', len(new_html), 'bytes')
print('Old had inline script at byte', last_script_start, 'to', last_script_end)
