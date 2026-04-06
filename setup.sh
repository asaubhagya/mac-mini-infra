#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_DIR="$SCRIPT_DIR/monitor"
VENV="$MONITOR_DIR/venv"
PLIST_SRC="$SCRIPT_DIR/com.macmini.monitor.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.macmini.monitor.plist"
LOG_DIR="$HOME/Library/Logs"

echo "==> Setting up Mac Mini Monitor"

# Create venv and install dependencies
echo "==> Creating Python virtual environment..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$MONITOR_DIR/requirements.txt"
echo "    Done."

# Install plist with real paths substituted
echo "==> Installing LaunchAgent..."
mkdir -p "$HOME/Library/LaunchAgents"
sed \
  -e "s|VENV_PYTHON|$VENV/bin/python|g" \
  -e "s|MONITOR_DIR|$MONITOR_DIR|g" \
  -e "s|LOG_DIR|$LOG_DIR|g" \
  "$PLIST_SRC" > "$PLIST_DST"

# Unload existing service if running
launchctl unload "$PLIST_DST" 2>/dev/null || true

# Load the service
launchctl load "$PLIST_DST"
echo "    LaunchAgent registered."

echo ""
echo "✓ Mac Mini Monitor is running at http://localhost:9090"
echo "  Logs: $LOG_DIR/mac-monitor.log"
echo "  To stop:    launchctl unload $PLIST_DST"
echo "  To restart: launchctl unload $PLIST_DST && launchctl load $PLIST_DST"
