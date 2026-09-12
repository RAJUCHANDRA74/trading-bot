#!/usr/bin/env python3
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

# Check what the engine is listening on
commands = [
    'netstat -tlnp 2>/dev/null | grep -E "8765|8766" || ss -tlnp | grep -E "8765|8766"',
    'curl -s http://127.0.0.1:8765/ | head -3',
    # Check if ufw has ports open
    'ufw status',
    # Try to bind engine to all interfaces - check current aiohttp binding
    'ps aux | grep sartrader | grep -v grep',
]

for cmd in commands:
    print(f'\n>>> {cmd[:80]}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=15)
        out = stdout2.read().decode('utf-8', errors='replace').strip()
        err = stderr2.read().decode('utf-8', errors='replace').strip()
        if out:
            print(out[:400])
        if err:
            if err.strip():
                print(f'  ERR: {err[:200]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

client.close()
