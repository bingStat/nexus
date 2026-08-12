#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://nexus.bings.app/bootstrap}"
INSTALL_DIR="${NEXUS_OPS_INSTALL_DIR:-/opt/nexus-ops}"
CONFIG_DIR="/etc/nexus"
STATE_DIR="/var/lib/nexus/ops"

mkdir -p "$INSTALL_DIR/ops/monitoring" "$CONFIG_DIR" "$STATE_DIR"
for file in __init__.py monitoring/__init__.py monitoring/common.py monitoring/snapshot.py monitoring/alerts.py monitoring/telegram.py monitoring/state_store.py; do
  mkdir -p "$INSTALL_DIR/ops/$(dirname "$file")"
  curl -fsSL "$SOURCE_BASE/ops/$file" -o "$INSTALL_DIR/ops/$file"
done
if [ ! -f "$CONFIG_DIR/ops.json" ]; then
  curl -fsSL "$SOURCE_BASE/ops/config.example.json" -o "$CONFIG_DIR/ops.json"
fi
chmod 600 "$CONFIG_DIR/ops.json"
for unit in nexus-health-snapshot.service nexus-health-snapshot.timer nexus-alert-engine.service nexus-alert-engine.timer nexus-telegram-bot.service nexus-telegram-bot.timer nexus-state-store.service nexus-state-store.timer; do
  curl -fsSL "$SOURCE_BASE/ops/systemd/$unit" -o "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now nexus-health-snapshot.timer nexus-alert-engine.timer nexus-telegram-bot.timer nexus-state-store.timer
systemctl start nexus-health-snapshot.service
systemctl start nexus-alert-engine.service
systemctl start nexus-state-store.service
printf 'Nexus ops installed. Configure %s; add %s only if Telegram alerts are wanted.\n' "$CONFIG_DIR/ops.json" "$CONFIG_DIR/telegram.token"
