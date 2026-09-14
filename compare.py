import urllib.request

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    served_body = resp.read()
    served_text = served_body.decode('utf-8')

# Find renderTlChart in served
start = served_text.find('function renderTlChart')
if start == -1:
    print("renderTlChart NOT FOUND in served file!")
else:
    end = served_text.find('\n/* ', start + 1)
    func = served_text[start:end]
    print("renderTlChart in served: " + str(len(func)) + " chars")
    # Show last 200 chars
    print("Last 200 chars of renderTlChart:")
    print(repr(func[-200:]))
