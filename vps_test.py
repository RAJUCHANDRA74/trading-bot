import paramiko, urllib.request

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=10)

# Check git log
stdin, stdout, stderr = client.exec_command('cd /home/sartrader/trading-bot && git log --oneline -3 && echo "---" && ls -la dashboard/dashboard.js')
print(stdout.read().decode())

client.close()

# Check VPS dashboard
try:
    req = urllib.request.Request('http://157.230.47.84:8765/dashboard.js', headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read()
        print("VPS dashboard.js size:", len(body), "bytes")
        print("First 50 bytes:", body[:50])
except Exception as e:
    print("VPS fetch error:", e)
