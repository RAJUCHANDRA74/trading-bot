import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=10)

# Check git log
stdin, stdout, stderr = client.exec_command('cd /home/sartrader/trading-bot && git log --oneline -3')
print("VPS git log:", stdout.read().decode().strip())

# Check dashboard.js size on VPS
stdin2, stdout2, stderr2 = client.exec_command('ls -la /home/sartrader/trading-bot/dashboard/dashboard.js')
print("VPS dashboard.js:", stdout2.read().decode().strip())

client.close()
