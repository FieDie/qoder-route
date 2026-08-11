#!/usr/bin/env bash
# restart.sh — kill the running QoderRoute server and start it fresh (prod).
# Usage: ./restart.sh
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8010
LOG="$BACKEND_DIR/data/server.log"
PIDFILE="$BACKEND_DIR/data/server.pid"
LOCKFILE="$BACKEND_DIR/data/server.lock"
FORCE_AFTER_SECONDS="${QODERROUTE_FORCE_RESTART_AFTER:-0}"

if ! [[ "$FORCE_AFTER_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "[!] QODERROUTE_FORCE_RESTART_AFTER must be a non-negative integer"
    exit 1
fi
FORCE_AFTER_SECONDS=$((10#$FORCE_AFTER_SECONDS))

same_process() {
    local pid="$1"
    local expected_start="$2"
    local actual_start
    [[ -r "/proc/$pid/stat" ]] || return 1
    actual_start="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
    [[ -n "$actual_start" && "$actual_start" == "$expected_start" ]]
}

mkdir -p "$BACKEND_DIR/data"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
    echo "[!] another QoderRoute start/restart is already running"
    exit 1
fi

echo "[*] stopping current server..."
OLD_PID=""
OLD_STARTTIME=""
if [[ -f "$PIDFILE" ]]; then
    CANDIDATE_PID="$(tr -d '[:space:]' < "$PIDFILE")"
    if [[ "$CANDIDATE_PID" =~ ^[0-9]+$ ]] && kill -0 "$CANDIDATE_PID" 2>/dev/null; then
        CMDLINE="$(tr '\0' ' ' < "/proc/$CANDIDATE_PID/cmdline" 2>/dev/null || true)"
        PROC_CWD="$(readlink -f "/proc/$CANDIDATE_PID/cwd" 2>/dev/null || true)"
        if [[ "$CMDLINE" == *"uvicorn app.main:app"* && "$PROC_CWD" == "$BACKEND_DIR" ]]; then
            OLD_PID="$CANDIDATE_PID"
            OLD_STARTTIME="$(awk '{print $22}' "/proc/$CANDIDATE_PID/stat")"
        else
            echo "[!] pidfile points to non-QoderRoute process $CANDIDATE_PID; refusing to kill it"
            exit 1
        fi
    fi
fi

if [[ -n "$OLD_PID" ]]; then
    kill "$OLD_PID" 2>/dev/null || true
    # Wait for the exact old process, not merely for Uvicorn to release 8010.
    # Releasing the listener happens before lifespan/SSE shutdown completes.
    WAIT_TICKS=0
    while same_process "$OLD_PID" "$OLD_STARTTIME"; do
        sleep 0.5
        WAIT_TICKS=$((WAIT_TICKS + 1))
        if (( WAIT_TICKS % 20 == 0 )); then
            echo "[*] waiting for old server pid $OLD_PID to finish active streams..."
        fi
        if (( FORCE_AFTER_SECONDS > 0 && WAIT_TICKS >= FORCE_AFTER_SECONDS * 2 )); then
            echo "[!] force timeout reached; killing exact old pid $OLD_PID"
            kill -9 "$OLD_PID" 2>/dev/null || true
            break
        fi
    done
    if same_process "$OLD_PID" "$OLD_STARTTIME"; then
        echo "[!] old server pid $OLD_PID did not exit; refusing to overlap backends"
        exit 1
    fi
fi

if ss -tln 2>/dev/null | grep -q ":$PORT "; then
    PIDS=$(ss -tlnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | sort -u || true)
    echo "[!] port $PORT is still owned by an unexpected process (${PIDS:-unknown}); refusing to kill it"
    exit 1
fi
echo "[*] port $PORT free"

echo "[*] starting server (prod, no reload)..."
cd "$BACKEND_DIR"
nohup setsid python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
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
