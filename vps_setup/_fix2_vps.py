#!/usr/bin/env python3
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

MSTOCK_API_KEY = "06SomqZj4ZsvaWc0se3gc0Y1OFbpAIj6CS8W8tQTI/M="
MSTOCK_TOTP_SECRET = "AF7NFEKUQBRDCXSRP2SVT5X7W7I7E632"

commands = [
    # Stop service
    'systemctl stop sartrader',
    # Backup logs if any
    'cp -r /home/sartrader/trading-bot/logs /tmp/trading-bot-logs 2>/dev/null || true',
    # Remove broken directory
    'rm -rf /home/sartrader/trading-bot',
    # Clone fresh
    'git clone https://github.com/RAJUCHANDRA74/trading-bot.git /home/sartrader/trading-bot 2>&1',
    # Restore logs
    'cp -r /tmp/trading-bot-logs /home/sartrader/trading-bot/logs 2>/dev/null || mkdir -p /home/sartrader/trading-bot/logs',
    # Create .env with credentials
    'cat > /home/sartrader/trading-bot/.env << ENVEOF\nMODE=PAPER\nMSTOCK_API_KEY=' + MSTOCK_API_KEY + '\nMSTOCK_TOTP_SECRET=' + MSTOCK_TOTP_SECRET + '\nENVEOF',
    'chown -R sartrader:sartrader /home/sartrader/trading-bot',
    'chmod 600 /home/sartrader/trading-bot/.env',
    # Check files are there
    'ls /home/sartrader/trading-bot/*.py 2>&1 | head -5',
    'ls /home/sartrader/trading-bot/sartrader/ 2>&1 | head -5',
    # Install deps
    'pip3 install --break-system-packages websockets upstox-python-sdk pandas schedule pytz requests python-dotenv -q 2>&1 | tail -3',
    # Restart
    'systemctl daemon-reload',
    'systemctl enable sartrader',
    'systemctl start sartrader',
    'sleep 8',
    'journalctl -u sartrader -n 40 --no-pager 2>&1 | tail -30',
    'systemctl status sartrader --no-pager 2>&1 | grep -E "Active:|Main PID|Loaded:"',
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
            if err.strip() and 'warning' not in err.lower()[:50]:
                print(f'  ERR: {err[:300]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

client.close()
print('\nDONE')
