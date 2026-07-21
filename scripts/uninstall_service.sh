#!/bin/bash
# Remove the Ceremyn dashboard LaunchAgent installed by install_service.sh.
# Usage: ./scripts/uninstall_service.sh
set -euo pipefail
LABEL="com.ceremyn.dashboard"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [ ! -f "$PLIST_PATH" ]; then
    echo "Not installed."
    exit 0
fi

launchctl unload "$PLIST_PATH" 2>/dev/null || true
rm "$PLIST_PATH"
echo "Uninstalled. The dashboard will no longer auto-start on login or auto-restart on crash."
echo "It is also stopped now -- use ./scripts/start_dashboard.sh to run it manually."
