#!/usr/bin/env bash
# =============================================================================
# setup_vps.sh — Run once on a FRESH Ubuntu 22.04 VPS to prepare it for SARTrader
# =============================================================================
# Usage: bash setup_vps.sh
# Run as: sudo bash setup_vps.sh
# =============================================================================

set -euo pipefail

echo "============================================"
echo "SARTrader VPS — Initial Setup"
echo "============================================"

# ── System update ────────────────────────────────────────────────────────────
echo "[1/8] Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

# ── Python 3.12 ─────────────────────────────────────────────────────────────
echo "[2/8] Installing Python 3.12..."
apt-get install -y software-properties-common -qq
add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
apt-get update -qq
apt-get install -y python3.12 python3.12-venv python3.12-dev python3-pip -qq
ln -sf /usr/bin/python3.12 /usr/local/bin/python 2>/dev/null || true

# ── pip packages ─────────────────────────────────────────────────────────────
echo "[3/8] Installing Python dependencies..."
pip3 install --upgrade pip -q
pip install websockets upstox-python-sdk pandas schedule pytz requests python-dotenv -q

# ── git + ufw + curl ────────────────────────────────────────────────────────
echo "[4/8] Installing git, ufw, curl..."
apt-get install -y git curl ufw fail2ban -qq

# ── Firewall (allow SSH, 8765, 8766) ────────────────────────────────────────
echo "[5/8] Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 8765/tcp comment 'SARTrader Dashboard'
ufw allow 8766/tcp comment 'SARTrader WebSocket'
ufw --force enable

# ── Create sartrader user ───────────────────────────────────────────────────
echo "[6/8] Creating 'sartrader' user..."
if id "sartrader" &>/dev/null; then
    echo "User 'sartrader' already exists — skipping"
else
    useradd -m -s /bin/bash -G sudo sartrader
    mkdir -p /home/sartrader
    chown sartrader:sartrader /home/sartrader
fi

# ── Swap file (1 GB) ────────────────────────────────────────────────────────
echo "[7/8] Configuring swap (1 GB)..."
if [ -f /swapfile ]; then
    echo "Swap already exists — skipping"
else
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ── timezone ────────────────────────────────────────────────────────────────
echo "[8/8] Setting timezone to Asia/Kolkata..."
timedatectl set-timezone Asia/Kolkata

echo ""
echo "============================================"
echo "✅ VPS base setup complete!"
echo "============================================"
echo "Next steps:"
echo "  1. Copy SSH public key to the server:"
echo "     ssh-copy-id sartrader@<your-vps-ip>"
echo "  2. Login as sartrader and run deploy.sh"
echo ""
