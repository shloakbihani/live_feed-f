#!/bin/bash
# Keep the EC200U USB modem awake. Usage: ./run_modem.sh start|stop|status|foreground
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/venv/bin/python"
PIDFILE="$DIR/logs/modem.pid"
LOG="$DIR/logs/modem.log"

mkdir -p "$DIR/logs"

is_running() {
  [ -f "$PIDFILE" ] || return 1
  kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

start() {
  if is_running; then
    echo "modem keepalive already running (pid $(cat "$PIDFILE"))"
    return 0
  fi
  nohup "$PY" -u "$DIR/modem_keepalive.py" >> "$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  echo "modem keepalive started (pid $(cat "$PIDFILE"))"
  echo "log: $LOG"
}

stop() {
  if is_running; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    sleep 0.3
    kill -9 "$(cat "$PIDFILE")" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  echo "modem keepalive stopped"
}

status() {
  if is_running; then
    echo "modem keepalive running (pid $(cat "$PIDFILE"))"
    return 0
  fi
  echo "modem keepalive stopped"
  return 1
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  foreground)
    exec "$PY" -u "$DIR/modem_keepalive.py"
    ;;
  *)
    echo "Usage: $0 start|stop|status|foreground" >&2
    exit 2
    ;;
esac
