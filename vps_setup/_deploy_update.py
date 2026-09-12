#!/usr/bin/env python3
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

commands = [
    'systemctl stop sartrader',
    'git config --global --add safe.directory /home/sartrader/trading-bot',
    'cd /home/sartrader/trading-bot && git pull origin main 2>&1',
    'chown -R sartrader:sartrader /home/sartrader/trading-bot',
    'systemctl start sartrader',
    'sleep 8',
    'journalctl -u sartrader -n 30 --no-pager 2>&1 | tail -20',
    'systemctl status sartrader --no-pager 2>&1 | grep -E "Active:|Main PID:"',
]

for cmd in commands:
    print(f'\n>>> {cmd[:80]}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=60)
        out = stdout2.read().decode('utf-8', errors='replace').strip()
        err = stderr2.read().decode('utf-8', errors='replace').strip()
        if out: print(out[:400])
        if err and err.strip() and 'warning' not in err.lower()[:40] and 'note' not in err.lower()[:40]:
            print(f'  ERR: {err[:200]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

client.close()
print('DONE')
