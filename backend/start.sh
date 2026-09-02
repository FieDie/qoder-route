#!/usr/bin/env bash
# start.sh — start the QoderRoute server (prod). Does nothing if already running.
# Usage: ./start.sh
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8010
LOG="$BACKEND_DIR/data/server.log"
PIDFILE="$BACKEND_DIR/data/server.pid"
LOCKFILE="$BACKEND_DIR/data/server.lock"

mkdir -p "$BACKEND_DIR/data"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
    echo "[!] another QoderRoute start/restart is already running"
    exit 1
fi

# already running?
if [[ -f "$PIDFILE" ]]; then
    EXISTING_PID="$(tr -d '[:space:]' < "$PIDFILE")"
    if [[ "$EXISTING_PID" =~ ^[0-9]+$ ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        CMDLINE="$(tr '\0' ' ' < "/proc/$EXISTING_PID/cmdline" 2>/dev/null || true)"
        PROC_CWD="$(readlink -f "/proc/$EXISTING_PID/cwd" 2>/dev/null || true)"
        if [[ "$CMDLINE" == *"uvicorn app.main:app"* && "$PROC_CWD" == "$BACKEND_DIR" ]]; then
            if curl -sf "http://127.0.0.1:$PORT/api/health" > /dev/null 2>&1; then
                echo "[✓] server already running (pid $EXISTING_PID) — http://0.0.0.0:$PORT"
                exit 0
            fi
            echo "[!] QoderRoute pid $EXISTING_PID is running but not ready"
            exit 1
        fi
    fi
fi
if ss -tln 2>/dev/null | grep -q ":$PORT "; then
    echo "[!] port $PORT is already in use by another process, not starting"
    exit 1
fi

# Prefer the project venv (README setup), then python3; bare `python` does not
# exist on stock Debian/Ubuntu. PYTHON=/path/to/python overrides.
if [[ -z "${PYTHON:-}" ]]; then
    if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
        PYTHON="$BACKEND_DIR/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON="$(command -v python3)"
    else
        PYTHON="$(command -v python || true)"
    fi
fi
if [[ -z "$PYTHON" ]]; then
    echo "[!] no python interpreter found (set PYTHON=/path/to/python)"
    exit 1
fi

echo "[*] starting server (prod, no reload)..."
cd "$BACKEND_DIR"
nohup setsid "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
    9>&- \
    >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"

# wait until it answers
for _ in $(seq 1 80); do
    if curl -sf "http://127.0.0.1:$PORT/api/health" > /dev/null 2>&1; then
        echo "[✓] server up (pid $(cat "$PIDFILE")) — http://0.0.0.0:$PORT"
        exit 0
    fi
    kill -0 "$(cat "$PIDFILE")" 2>/dev/null || break
    sleep 0.5
done

echo "[!] server did not become ready in 40s — last log lines:"
tail -20 "$LOG"
exit 1
