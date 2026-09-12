#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Deploy (or update) SARTrader on the VPS
# =============================================================================
# Usage: bash deploy.sh
# Run as: sartrader user (not root)
# =============================================================================

set -euo pipefail

APP_DIR="/home/sartrader/trading-bot"
SERVICE_NAME="sartrader"

# ── Colours ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Check env file ───────────────────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    die "Missing $APP_DIR/.env — copy .env.vps.template to .env and fill in your secrets"
fi

# ── Stop existing service ────────────────────────────────────────────────────
info "Stopping existing engine (if running)..."
sudo systemctl stop $SERVICE_NAME 2>/dev/null || true

# ── Pull latest code ─────────────────────────────────────────────────────────
info "Pulling latest code from GitHub..."
cd $APP_DIR
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
git stash 2>/dev/null || true
git pull origin main

# ── Install / upgrade Python dependencies ────────────────────────────────────
info "Installing Python dependencies..."
pip install --upgrade pip -q
pip install websockets upstox-python-sdk pandas schedule pytz requests python-dotenv -q 2>&1 | tail -3

# ── Create log directory ─────────────────────────────────────────────────────
mkdir -p $APP_DIR/logs

# ── Reload systemd, start service ───────────────────────────────────────────
info "Reloading systemd and starting SARTrader..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl start $SERVICE_NAME

# ── Verify ───────────────────────────────────────────────────────────────────
sleep 5
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    info "✅ SARTrader engine is running!"
    sudo systemctl status $SERVICE_NAME --no-pager | head -10
else
    warn "Engine may not have started cleanly — check logs:"
    sudo journalctl -u $SERVICE_NAME -n 20 --no-pager
fi

# ── Firewall check ───────────────────────────────────────────────────────────
info "Checking firewall..."
sudo ufw status | grep -E "8765|8766" || warn "Ports 8765/8766 not found in ufw rules"
