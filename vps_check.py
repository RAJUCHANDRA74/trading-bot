import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

# Check service
stdin, stdout, stderr = client.exec_command('sudo systemctl is-active sartrader')
print('Service active:', stdout.read().decode().strip())

# Check ports
stdin2, stdout2, stderr2 = client.exec_command('ss -tlnp')
lines = stdout2.read().decode().split('\n')
for line in lines:
    if '8765' in line or '8766' in line:
        print('Port:', line.strip())

# Check git version
stdin3, stdout3, stderr3 = client.exec_command('cd /home/sartrader/trading-bot && git log --oneline -3')
print('Git log:', stdout3.read().decode().strip())

client.close()
