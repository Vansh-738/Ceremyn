#!/bin/bash
# Install AlphaQuant's dashboard as a macOS LaunchAgent: starts automatically on
# login and restarts automatically if it ever crashes. Unlike start_dashboard.sh's
# plain `nohup ... &`, this survives a reboot and needs no supervision -- launchd
# does the restarting.
#
# Once installed, manage the service with launchctl, not start_dashboard.sh /
# stop_dashboard.sh (those talk directly to the process; launchd would just start
# it right back up behind them). Use ./scripts/uninstall_service.sh to remove it.
#
# Usage: ./scripts/install_service.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
LABEL="com.alphaquant.dashboard"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [ ! -x "$PROJECT_DIR/.venv/bin/uvicorn" ]; then
    echo "No .venv/bin/uvicorn found in $PROJECT_DIR -- set up the venv first." >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_DIR}/.venv/bin/python3.12</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>alphaquant.api.main:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8000</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>/tmp/alphaquant.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/alphaquant.log</string>
</dict>
</plist>
EOF

# Stop any manually-started instance first so launchd doesn't fight over port 8000.
if pgrep -f "uvicorn alphaquant.api.main:app" > /dev/null; then
    pkill -f "uvicorn alphaquant.api.main:app"
    sleep 1
fi

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed as a LaunchAgent -- it will auto-start on login and auto-restart on crash."
echo "Dashboard: http://127.0.0.1:8000/dashboard/"
echo "Logs: tail -f /tmp/alphaquant.log"
echo "Status: launchctl list | grep alphaquant"
echo "To remove: ./scripts/uninstall_service.sh"
