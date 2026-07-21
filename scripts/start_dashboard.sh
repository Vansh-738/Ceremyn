#!/bin/bash
# Start AlphaQuant's dashboard + paper-trading poller in the background.
# Usage: ./scripts/start_dashboard.sh
#
# If you've run install_service.sh, launchd already keeps this running (and
# restarts it on crash/reboot) -- this script isn't needed and won't conflict,
# but manage the service via launchctl/uninstall_service.sh instead of this
# script's stop_dashboard.sh counterpart.
set -euo pipefail
cd "$(dirname "$0")/.."

if launchctl list 2>/dev/null | grep -q com.alphaquant.dashboard; then
    echo "Managed by launchd (install_service.sh) -- already running and self-restarting."
    echo "Open http://127.0.0.1:8000/dashboard/"
    exit 0
fi

if pgrep -f "uvicorn alphaquant.api.main:app" > /dev/null; then
    echo "Already running. Open http://127.0.0.1:8000/dashboard/"
    echo "(To restart: ./scripts/stop_dashboard.sh, then run this again.)"
    exit 0
fi

nohup .venv/bin/uvicorn alphaquant.api.main:app --host 127.0.0.1 --port 8000 \
    > /tmp/alphaquant.log 2>&1 &
disown
sleep 2

if curl -s http://127.0.0.1:8000/health > /dev/null; then
    echo "Started. Open http://127.0.0.1:8000/dashboard/ in your browser."
    echo "Logs: tail -f /tmp/alphaquant.log"
else
    echo "Something went wrong — check /tmp/alphaquant.log"
    exit 1
fi
