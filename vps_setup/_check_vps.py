#!/usr/bin/env python3
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

commands = [
    # Check sartrader module structure
    'ls -la /home/sartrader/trading-bot/sartrader/ 2>&1 | head -15',
    'cat /home/sartrader/trading-bot/sartrader/__init__.py 2>&1 | head -5',
    # Test if module is importable
    'cd /home/sartrader/trading-bot && python3 -c "import sartrader; print(sartrader)" 2>&1',
    'cd /home/sartrader/trading-bot && python3 -c "import sartrader.config; print(sartrader.config.MODE)" 2>&1',
    # Check PYTHONPATH
    'echo $PYTHONPATH',
    'cd /home/sartrader/trading-bot && PYTHONPATH=/home/sartrader/trading-bot python3 -c "import sartrader.engine; print(\'engine OK\')" 2>&1',
]

for cmd in commands:
    print(f'\n>>> {cmd[:90].replace(chr(10), " ")}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=30)
        out = stdout2.read().decode('utf-8', errors='replace').strip()
        err = stderr2.read().decode('utf-8', errors='replace').strip()
        if out:
            print(out[:400])
        if err:
            if err.strip():
                print(f'  ERR: {err[:300]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

client.close()
