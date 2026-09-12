#!/usr/bin/env python3
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

MSTOCK_API_KEY = "06SomqZj4ZsvaWc0se3gc0Y1OFbpAIj6CS8W8tQTI/M="
MSTOCK_TOTP_SECRET = "AF7NFEKUQBRDCXSRP2SVT5X7W7I7E632"

commands = [
    # Check what's in /home/sartrader
    'ls -la /home/sartrader/ 2>&1 | head -20',
    # Check if trading-bot exists
    'ls /home/sartrader/trading-bot/ 2>&1 | head -10',
    # Create .env in the right location
    'mkdir -p /home/sartrader/trading-bot',
    'cat > /home/sartrader/trading-bot/.env << ENVEOF\nMODE=PAPER\nMSTOCK_API_KEY=' + MSTOCK_API_KEY + '\nMSTOCK_TOTP_SECRET=' + MSTOCK_TOTP_SECRET + '\nENVEOF',
    'chown sartrader:sartrader /home/sartrader/trading-bot/.env',
    'chmod 600 /home/sartrader/trading-bot/.env',
    'cat /home/sartrader/trading-bot/.env',
    # Install deps with --break-system-packages (Ubuntu 24.04)
    'pip3 install --break-system-packages websockets upstox-python-sdk pandas schedule pytz requests python-dotenv -q 2>&1 | tail -5',
    # Restart service
    'systemctl restart sartrader',
    'sleep 5',
    'journalctl -u sartrader -n 20 --no-pager 2>&1 | grep -E "ERROR|WARN|INFO|started"',
    'systemctl status sartrader --no-pager 2>&1 | grep -E "Active:|Main PID:|Loaded:"',
]

for cmd in commands:
    print(f'\n>>> {cmd[:90].replace(chr(10), " ")}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=120)
        out = stdout2.read().decode('utf-8', errors='replace').strip()
        err = stderr2.read().decode('utf-8', errors='replace').strip()
        if out:
            print(out[:500])
        if err:
            if err.strip():
                print(f'  ERR: {err[:300]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

client.close()
print('\nDONE')
