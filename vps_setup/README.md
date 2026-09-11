# SARTrader — VPS Setup Guide

## Overview

This folder contains everything needed to run SARTrader 24/7 on a **DigitalOcean Ubuntu 22.04 VPS**.

---

## What You Need

1. **DigitalOcean account** — [sign up here](https://www.digitalocean.com)
2. **M-Stock API key + TOTP secret** — from your M-Stock dashboard
3. **A domain name (optional)** — for accessing the dashboard publicly

---

## Step 1 — Create the Droplet

1. Log in to [DigitalOcean](https://www.digitalocean.com)
2. Click **Create → Droplets**
3. **Choose Region**: Singapore (closest to NSE)
4. **Choose Image**: Ubuntu 22.04 LTS (x64)
5. **Choose Size**: Basic — $6/mo (1 GB RAM, 1 vCPU, 25 GB SSD)
   - *Upgrade later if needed*
6. **Choose Authentication**: SSH Keys
   - Click **New SSH Key**
   - On your Windows machine, run: `Get-Content $env:USERPROFILE\.ssh\id_rsa.pub`
   - Paste the contents into DigitalOcean
   - Give it a name like "Rajkumar-Windows"
7. **Finalize**: 1 droplet, no backups (cheaper, add later)
8. **Hostname**: `sartrader`
9. Click **Create Droplet** — note the IP address shown

---

## Step 2 — Initial VPS Setup (One Time)

SSH into your VPS as root:

```bash
# Replace 159.x.x.x with your droplet's IP
ssh root@159.x.x.x
```

Run the setup script:

```bash
bash < /dev/null
# Then paste:
wget -qO- https://raw.githubusercontent.com/RAJUCHANDRA74/trading-bot/main/vps_setup/setup_vps.sh | bash
```

This will:
- Install Python 3.12
- Install git, pip, firewall (ufw)
- Create `sartrader` user
- Configure 1 GB swap file
- Set timezone to Asia/Kolkata

---

## Step 3 — Add SSH Key to sartrader User

On your Windows machine, copy your SSH public key to the VPS:

```powershell
# Get your public key
Get-Content $env:USERPROFILE\.ssh\id_rsa.pub

# If you don't have one yet, generate it:
ssh-keygen -t rsa -b 4096
```

Then on the VPS (as root):

```bash
# Create .ssh directory for sartrader user
mkdir -p /home/sartrader/.ssh
chmod 700 /home/sartrader/.ssh

# Paste your public key (from Windows)
nano /home/sartrader/.ssh/authorized_keys
# Paste the contents, save (Ctrl+X, Y, Enter)

chmod 600 /home/sartrader/.ssh/authorized_keys
chown -R sartrader:sartrader /home/sartrader/.ssh
```

---

## Step 4 — Clone the Repository

SSH as **sartrader user**:

```bash
ssh sartrader@159.x.x.x

# Clone the repo
git clone https://github.com/RAJUCHANDRA74/trading-bot.git
cd trading-bot
```

---

## Step 5 — Configure Environment

```bash
# Copy the template
cp vps_setup/.env.vps.template .env

# Edit with your M-Stock credentials
nano .env
```

Fill in:
- `MSTOCK_API_KEY` — your M-Stock API key
- `MSTOCK_TOTP_SECRET` — 32-character TOTP secret
- `MODE=PAPER` — change to `LIVE` when ready for real orders

---

## Step 6 — Install Python Dependencies

```bash
pip install websockets upstox-python-sdk pandas schedule pytz requests python-dotenv -q
```

---

## Step 7 — Install the Systemd Service

```bash
# As root:
sudo cp /home/sartrader/trading-bot/vps_setup/sartrader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sartrader
sudo systemctl start sartrader

# Check status:
sudo systemctl status sartrader --no-pager
```

---

## Step 8 — Open Firewall Ports

```bash
sudo ufw allow ssh
sudo ufw allow 8765/tcp comment 'SARTrader Dashboard'
sudo ufw allow 8766/tcp comment 'SARTrader WebSocket'
sudo ufw enable
sudo ufw status
```

---

## Step 9 — Verify It's Running

```bash
# Check service status
sudo systemctl status sartrader

# View live logs
sudo journalctl -u sartrader -f

# Test dashboard (from browser):
# http://159.x.x.x:8765
```

---

## Daily Operations

### Restart the engine
```bash
sudo systemctl restart sartrader
```

### View logs
```bash
# Real-time
sudo journalctl -u sartrader -f

# Last 100 lines
sudo journalctl -u sartrader -n 100 --no-pager
```

### Stop / Start
```bash
sudo systemctl stop sartrader
sudo systemctl start sartrader
```

### Update code and restart
```bash
cd /home/sartrader/trading-bot
bash vps_setup/deploy.sh
```

---

## Updating the VPS After Code Changes

From your Windows machine:

```bash
ssh sartrader@159.x.x.x
cd ~/trading-bot
git pull origin main
# Dependencies are auto-installed by systemd / deploy.sh
sudo systemctl restart sartrader
```

Or use `deploy.sh`:
```bash
bash vps_setup/deploy.sh
```

---

## Going LIVE with M-Stock

Before going LIVE on VPS:

1. **IP Whitelist**: Add your VPS IP to M-Stock API settings
   - Login to M-Stock → API Settings → Whitelist IP → add `159.x.x.x`

2. **Change mode**:
   ```bash
   nano ~/trading-bot/.env
   # Change: MODE=LIVE
   sudo systemctl restart sartrader
   ```

3. **Verify**: Check logs — you should see `Mode: LIVE` on startup

---

## Monitoring

### Free External Monitoring
- Use **UptimeRobot** (uptimerobot.com) — free plan monitors 50 sites
- Add monitor for `http://159.x.x.x:8765` — alerts you if engine goes down

### Telegram Alerts (optional)
Add a simple script to send alerts when the service crashes:
```bash
# In systemd service, add to ExecStartPost:
curl -s -X POST https://api.telegram.org/bot<TOKEN>/sendMessage \
  -d "chat_id=<CHAT_ID>&text=SARTrader restarted on VPS"
```

---

## Troubleshooting

### "Connection refused" on port 8765
```bash
sudo systemctl status sartrader
sudo journalctl -u sartrader -n 30 --no-pager
# Common cause: .env missing or wrong API key
```

### M-Stock IA403 error
- Home IP not whitelisted on M-Stock API settings
- Add VPS IP to whitelist: M-Stock → API Settings → IP Whitelist

### Engine restarts repeatedly
```bash
sudo journalctl -u sartrader -n 50 --no-pager
# Look for Python errors
```

### RAM issues (1GB VPS)
```bash
# Check memory
free -h
# If OOM: upgrade droplet to 2GB
```

---

## Estimated Monthly Cost

| Item | Cost |
|------|------|
| DigitalOcean Basic (1 GB RAM) | $6/mo |
| Domain name (optional) | $1/mo |
| Total | **~$7/mo** |
