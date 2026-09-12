#!/usr/bin/env python3
import paramiko, io

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

# Update systemd service to bind on all interfaces (0.0.0.0)
service_content = """[Unit]
Description=SARTrader Trading Engine
After=network.target

[Service]
Type=simple
User=sartrader
Group=sartrader
WorkingDirectory=/home/sartrader/trading-bot
EnvironmentFile=/home/sartrader/trading-bot/.env
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sartrader
ExecStart=/usr/bin/python3 -m sartrader.engine --host 0.0.0.0 --port 8765

[Install]
WantedBy=multi-user.target
"""

sftp = client.open_sftp()
sftp.putfo(io.BytesIO(service_content.encode('utf-8')), '/etc/systemd/system/sartrader.service')
sftp.close()

# Reload and restart
commands = [
    'chmod 644 /etc/systemd/system/sartrader.service',
    'systemctl daemon-reload',
    'systemctl restart sartrader',
    'sleep 5',
    'ss -tlnp | grep -E "8765|8766"',
    'systemctl status sartrader --no-pager 2>&1 | grep -E "Active:|Main PID:"',
    'journalctl -u sartrader -n 10 --no-pager 2>&1',
]

for cmd in commands:
    print(f'\n>>> {cmd[:80]}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=30)
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
print('\nDONE')
