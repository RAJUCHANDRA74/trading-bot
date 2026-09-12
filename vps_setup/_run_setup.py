#!/usr/bin/env python3
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('157.230.47.84', username='root', password='CHIKANI@123c', timeout=15)

commands = [
    'apt-get update -qq',
    'apt-get install -y git curl ufw fail2ban',
    # Firewall
    'ufw --force enable',
    'ufw default deny incoming',
    'ufw default allow outgoing',
    'ufw allow ssh',
    'ufw allow 8765/tcp comment "SARTrader Dashboard"',
    'ufw allow 8766/tcp comment "SARTrader WebSocket"',
    # Create user
    'id sartrader 2>/dev/null && echo "sartrader exists" || useradd -m -s /bin/bash -G sudo sartrader',
    'mkdir -p /home/sartrader && chown -R sartrader:sartrader /home/sartrader',
    # Swap
    'ls /swapfile 2>/dev/null && echo "swap exists" || (fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo "/swapfile none swap sw 0 0" >> /etc/fstab && echo "swap created")',
    # Timezone
    'timedatectl set-timezone Asia/Kolkata',
    'date',
    'python3 --version',
    'free -h',
]

for cmd in commands:
    print(f'\n>>> {cmd[:70]}')
    try:
        stdin2, stdout2, stderr2 = client.exec_command(cmd, timeout=60)
        out = stdout2.read().decode().strip()
        err = stderr2.read().decode().strip()
        if out:
            print(out)
        if err:
            # Filter out boring warnings
            if 'warning' not in err.lower()[:50] and err.strip():
                print(f'  ERR: {err[:200]}')
    except Exception as e:
        print(f'  EXCEPTION: {e}')

client.close()
print('\nDONE')
