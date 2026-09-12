#!/usr/bin/env python3
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

commands = [
    'systemctl status sartrader --no-pager 2>&1 | grep -E "Active:|Main PID:|Loaded:"',
    'journalctl -u sartrader -n 5 --no-pager 2>&1',
    'ss -tlnp | grep -E "8765|8766"',
    'free -h',
]

for cmd in commands:
    print(f'\n>>> {cmd[:80]}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=15)
        out = stdout2.read().decode('utf-8', errors='replace').strip()
        err = stderr2.read().decode('utf-8', errors='replace').strip()
        if out: print(out[:300])
        if err and err.strip() and 'warning' not in err.lower()[:30]: print(f'  ERR: {err[:150]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

client.close()
print('\nDONE')
