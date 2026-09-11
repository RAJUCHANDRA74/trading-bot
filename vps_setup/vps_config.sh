# =============================================================================
# vps_config.sh — Your VPS connection details
# =============================================================================
# Update VPS_HOST with your DigitalOcean droplet IP
# =============================================================================

export VPS_HOST="YOUR_VPS_IP_HERE"
export VPS_USER="sartrader"
export VPS_PORT="22"

# ── Quick SSH command ────────────────────────────────────────────────────────
# ssh $VPS_USER@$VPS_HOST

# ── Quick deploy (from Windows local repo) ───────────────────────────────────
# scp .env $VPS_USER@$VPS_HOST:~/trading-bot/.env
# ssh $VPS_USER@$VPS_HOST "cd ~/trading-bot && git pull && sudo systemctl restart sartrader"
