#!/usr/bin/env python3
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

# M-Stock credentials (from config.py)
MSTOCK_API_KEY = "06SomqZj4ZsvaWc0se3gc0Y1OFbpAIj6CS8W8tQTI/M="
MSTOCK_TOTP_SECRET = "AF7NFEKUQBRDCXSRP2SVT5X7W7I7E632"

commands = [
    # Clone repo as sartrader user
    'cd /home/sartrader && git clone https://github.com/RAJUCHANDRA74/trading-bot.git . 2>&1 || echo "Repo already exists"',
    # Create .env file with credentials
    'cat > /home/sartrader/trading-bot/.env << \'ENVEOF\'\nMODE=PAPER\nMSTOCK_API_KEY=' + MSTOCK_API_KEY + '\nMSTOCK_TOTP_SECRET=' + MSTOCK_TOTP_SECRET + '\nENVEOF',
    'chown sartrader:sartrader /home/sartrader/trading-bot/.env',
    'chmod 600 /home/sartrader/trading-bot/.env',
    # Install Python deps
    'pip3 install websockets upstox-python-sdk pandas schedule pytz requests python-dotenv -q 2>&1 | tail -5',
    # Create logs dir
    'mkdir -p /home/sartrader/trading-bot/logs',
    'chown -R sartrader:sartrader /home/sartrader/trading-bot',
    # Update systemd service to use .env
    'cat > /etc/systemd/system/sartrader.service << \'SVCEOF\'\n[Unit]\nDescription=SARTrader Trading Engine\nAfter=network.target\n\n[Service]\nType=simple\nUser=sartrader\nGroup=sartrader\nWorkingDirectory=/home/sartrader/trading-bot\nEnvironmentFile=/home/sartrader/trading-bot/.env\nRestart=on-failure\nRestartSec=5\nStandardOutput=journal\nStandardError=journal\nSyslogIdentifier=sartrader\nExecStart=/usr/bin/python3 -m sartrader.engine\n\n[Install]\nWantedBy=multi-user.target\nSVCEOF',
    'chmod 644 /etc/systemd/system/sartrader.service',
    'systemctl daemon-reload',
    'systemctl enable sartrader',
]

for cmd in commands:
    label = cmd[:80].replace('\n', ' ')
    print(f'\n>>> {label}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=120)
        out = stdout2.read().decode('utf-8', errors='replace').strip()
        err = stderr2.read().decode('utf-8', errors='replace').strip()
        if out:
            print(out[:400])
        if err:
            if err.strip():
                print(f'  ERR: {err[:200]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

# Start the service and check status
print('\n\n=== Starting service ===')
for cmd in [
    'systemctl start sartrader',
    'sleep 3',
    'systemctl status sartrader --no-pager 2>&1 | head -20',
    'journalctl -u sartrader -n 30 --no-pager 2>&1',
]:
    print(f'\n>>> {cmd[:70]}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=30)
        out = stdout2.read().decode('utf-8', errors='replace').strip()
        err = stderr2.read().decode('utf-8', errors='replace').strip()
        if out:
            print(out[:500])
        if err:
            if err.strip():
                print(f'  ERR: {err[:200]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

client.close()
print('\nDONE')
