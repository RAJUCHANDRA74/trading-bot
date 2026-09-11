#!/usr/bin/env bash
# =============================================================================
# install_service.sh — Run ONCE on VPS as root after running setup_vps.sh
# =============================================================================
# Usage: sudo bash install_service.sh
# =============================================================================

set -euo pipefail

SERVICE_FILE="/home/sartrader/trading-bot/vps_setup/sartrader.service"
APP_DIR="/home/sartrader/trading-bot"

echo "============================================"
echo "Installing SARTrader systemd service"
echo "============================================"

# ── Copy service file ────────────────────────────────────────────────────────
cp $SERVICE_FILE /etc/systemd/system/sartrader.service
chmod 644 /etc/systemd/system/sartrader.service

# ── Reload systemd ───────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl daemon-reexec

# ── Enable and start ─────────────────────────────────────────────────────────
systemctl enable sartrader
systemctl start sartrader

echo ""
echo "============================================"
echo "Service installed. Verifying..."
echo "============================================"
sleep 3
systemctl status sartrader --no-pager

echo ""
echo "Dashboard: http://$(curl -s ifconfig.me):8765"
echo "WebSocket: ws://$(curl -s ifconfig.me):8766"
