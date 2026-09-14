import urllib.request

url = "http://127.0.0.1:8765/dashboard.js"
with urllib.request.urlopen(url, timeout=5) as resp:
    body = resp.read()

with open('served_dashboard.js', 'wb') as f:
    f.write(body)

text = body.decode('utf-8')
lines = text.split('\n')

print("Served file has", len(lines), "lines")
print("Size:", len(text), "chars")

# Check lines 1075-1130
print("\n=== Lines 1075-1130 ===")
for i in range(1074, min(1130, len(lines))):
    line = lines[i]
    # Replace problematic chars for display
    clean = line.replace('\u20b9','Rs').replace('\u25cf','*').replace('\u2014','--').replace('\u2013','-').replace('\u2019',"'").replace('\u2018',"'").replace('\u201c','"').replace('\u201d','"')
    print("%4d: %s" % (i+1, clean[:120]))
