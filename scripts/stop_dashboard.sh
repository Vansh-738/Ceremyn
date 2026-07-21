#!/bin/bash
# Stop AlphaQuant's dashboard + paper-trading poller.
# Usage: ./scripts/stop_dashboard.sh
if launchctl list 2>/dev/null | grep -q com.alphaquant.dashboard; then
    echo "Managed by launchd (install_service.sh) -- killing the process here would just"
    echo "get it restarted automatically. Use ./scripts/uninstall_service.sh instead,"
    echo "or 'launchctl stop com.alphaquant.dashboard' to pause it temporarily."
    exit 1
fi

if pgrep -f "uvicorn alphaquant.api.main:app" > /dev/null; then
    pkill -f "uvicorn alphaquant.api.main:app"
    echo "Stopped."
else
    echo "Not running."
fi
