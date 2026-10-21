#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_LABEL="com.ceremyn.dashboard"
APP_HOST="127.0.0.1"
APP_PORT="8000"
APP_URL="http://${APP_HOST}:${APP_PORT}"
HEALTH_URL="${APP_URL}/health"
STATUS_URL="${APP_URL}/system/status"
LOG_PATH="/tmp/ceremyn.log"
UVICORN_PATTERN="uvicorn ceremyn.api.main:app"

cd "$ROOT_DIR"

print_usage() {
    cat <<'USAGE'
Usage: ./scripts/ceremyn.sh <command>

Commands:
  doctor    Check local Ceremyn prerequisites and config hints
  start     Start Ceremyn locally in the background
  stop      Stop a manually started Ceremyn process
  restart   Restart Ceremyn
  status    Show process and API status
  logs      Tail Ceremyn logs
  open      Open the dashboard URL
  install   Install Ceremyn as a macOS LaunchAgent
  uninstall Remove the macOS LaunchAgent
USAGE
}

is_launchd_managed() {
    # Consume the whole pipe: grep -q can SIGPIPE launchctl under pipefail.
    launchctl list 2>/dev/null | grep -F "$APP_LABEL" >/dev/null
}

is_process_running() {
    pgrep -f "$UVICORN_PATTERN" >/dev/null 2>&1
}

require_file() {
    local path="$1"
    local hint="$2"
    if [ -e "$path" ]; then
        echo "[ok]   $path"
    else
        echo "[miss] $path — $hint"
        return 1
    fi
}

print_http_status() {
    if curl -fsS "$STATUS_URL" >/tmp/ceremyn-status.json 2>/dev/null; then
        echo "[ok]   API reachable at $STATUS_URL"
        cat /tmp/ceremyn-status.json
        echo
    else
        echo "[miss] API not responding at $STATUS_URL"
        return 1
    fi
}

run_doctor() {
    local failed=0
    echo "Ceremyn doctor"
    echo "root: $ROOT_DIR"
    echo

    require_file "$ROOT_DIR/.env" "copy .env.example to .env and fill your settings" || failed=1
    require_file "$ROOT_DIR/.venv/bin/python3.12" "create the Python 3.12 virtualenv" || failed=1
    require_file "$ROOT_DIR/.venv/bin/uvicorn" "install dependencies into the virtualenv" || failed=1

    # The app only reads CEREMYN_* variables; anything still using the pre-rename
    # prefix is silently ignored, which looks like "my credentials don't work".
    if grep -q '^ALPHAQUANT_' "$ROOT_DIR/.env" 2>/dev/null; then
        echo "[fail] .env still uses old ALPHAQUANT_ variable names — rename the prefixes:"
        echo "       sed -i '' 's/^ALPHAQUANT_/CEREMYN_/' .env"
        failed=1
    fi

    if command -v docker >/dev/null 2>&1; then
        echo "[ok]   docker is installed"
    else
        echo "[warn] docker is not installed — integration services may be unavailable"
    fi

    if grep -Eq '^CEREMYN_KITE__API_KEY=$' .env 2>/dev/null; then
        echo "[warn] Kite API key looks empty in .env"
    else
        echo "[ok]   Kite API key is set"
    fi

    if grep -Eq '^CEREMYN_KITE__ACCESS_TOKEN=$' .env 2>/dev/null; then
        echo "[warn] Kite access token is empty — run scripts/kite_login.py on trading days"
    fi

    if is_launchd_managed; then
        echo "[ok]   launchd service installed: $APP_LABEL"
    else
        echo "[info] launchd service not installed — use ./scripts/ceremyn.sh install for auto-start"
    fi

    if is_process_running; then
        echo "[ok]   Ceremyn process is running"
        print_http_status || failed=1
    else
        echo "[info] Ceremyn process is not running"
    fi

    if [ "$failed" -ne 0 ]; then
        echo
        echo "Doctor found issues that should be fixed before daily use."
        exit 1
    fi

    echo
    echo "Ceremyn looks ready for day-to-day use."
}

run_start() {
    "$ROOT_DIR/scripts/start_dashboard.sh"
}

run_stop() {
    "$ROOT_DIR/scripts/stop_dashboard.sh"
}

run_restart() {
    if is_launchd_managed; then
        launchctl kickstart -k "gui/$(id -u)/$APP_LABEL"
        echo "Restarted launchd-managed Ceremyn service."
    else
        "$ROOT_DIR/scripts/stop_dashboard.sh" || true
        "$ROOT_DIR/scripts/start_dashboard.sh"
    fi
}

run_status() {
    echo "Ceremyn status"
    echo "root: $ROOT_DIR"
    if is_launchd_managed; then
        echo "service: launchd-managed ($APP_LABEL)"
    else
        echo "service: manual"
    fi

    if is_process_running; then
        echo "process: running"
    else
        echo "process: stopped"
    fi

    print_http_status || true

    if [ -f "$LOG_PATH" ]; then
        echo "logs: $LOG_PATH"
    else
        echo "logs: not created yet"
    fi
}

run_logs() {
    if [ -f "$LOG_PATH" ]; then
        tail -f "$LOG_PATH"
    else
        echo "No log file yet at $LOG_PATH"
        exit 1
    fi
}

run_open() {
    open "${APP_URL}/dashboard/"
}

run_install() {
    "$ROOT_DIR/scripts/install_service.sh"
}

run_uninstall() {
    "$ROOT_DIR/scripts/uninstall_service.sh"
}

command="${1:-}"
case "$command" in
    doctor)
        run_doctor
        ;;
    start)
        run_start
        ;;
    stop)
        run_stop
        ;;
    restart)
        run_restart
        ;;
    status)
        run_status
        ;;
    logs)
        run_logs
        ;;
    open)
        run_open
        ;;
    install)
        run_install
        ;;
    uninstall)
        run_uninstall
        ;;
    ""|-h|--help|help)
        print_usage
        ;;
    *)
        echo "Unknown command: $command" >&2
        echo
        print_usage
        exit 1
        ;;
esac
