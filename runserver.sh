#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
MODEL_DIR="$ROOT/codet5_commenst_expla/checkpoint_best"

export MODEL_PATH="$MODEL_DIR"
export TOKENIZER_PATH="$MODEL_DIR"

LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/server.log"
PID_FILE="$ROOT/.server.pid"

is_windows() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

venv_python() {
  if [ -x ".venv/bin/python" ]; then
    echo ".venv/bin/python"
  elif [ -x ".venv/Scripts/python.exe" ]; then
    echo ".venv/Scripts/python.exe"
  else
    echo ""
  fi
}

find_pids_by_port() {
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti tcp:"$PORT" | sort -u || true)
  elif is_windows && command -v netstat >/dev/null 2>&1; then
    pids=$(netstat -ano | awk -v port=":$PORT" '$1 ~ /TCP/ && $2 ~ port && $4 == "LISTENING" {print $5}' | sort -u || true)
  fi
  echo "$pids"
}

stop_pid() {
  local pid="$1"
  if [ -z "$pid" ]; then
    return 0
  fi
  if is_windows; then
    taskkill /PID "$pid" /F >/dev/null 2>&1 || true
  else
    kill "$pid" >/dev/null 2>&1 || true
  fi
}

stop_pids() {
  local pids="$1"
  if [ -z "$pids" ]; then
    return 0
  fi
  while IFS= read -r pid; do
    if [ -n "$pid" ]; then
      stop_pid "$pid"
    fi
  done <<< "$pids"
}

start_server() {
  local venv_py
  venv_py="$(venv_python)"
  if [ -z "$venv_py" ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
  fi

  mkdir -p "$LOG_DIR"

  if [ ! -d "$MODEL_DIR" ]; then
    echo "Model directory not found: $MODEL_DIR"
    echo "Run ./setup.sh to extract or provide the model files."
  fi

  local port_pids
  port_pids="$(find_pids_by_port)"
  if [ -n "$port_pids" ]; then
    echo "Port $PORT is in use by PID(s): $(echo "$port_pids" | tr '\n' ' ')"
    stop_pids "$port_pids"
  fi

  echo "Starting server on port $PORT..."
  "$venv_py" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  echo "Server started with PID $(cat "$PID_FILE"). Logs: $LOG_FILE"
}

stop_server() {
  local pid=""
  if [ -f "$PID_FILE" ]; then
    pid="$(cat "$PID_FILE")"
  fi

  if [ -z "$pid" ]; then
    pid="$(find_pids_by_port)"
  fi

  if [ -z "$pid" ]; then
    echo "No server process found."
    return 0
  fi

  if [ -f "$PID_FILE" ]; then
    echo "Stopping server (PID $pid)..."
    stop_pid "$pid"
  else
    echo "Stopping server on port $PORT (PID(s): $(echo "$pid" | tr '\n' ' '))..."
    stop_pids "$pid"
  fi
  rm -f "$PID_FILE"
}

status_server() {
  local pid=""
  if [ -f "$PID_FILE" ]; then
    pid="$(cat "$PID_FILE")"
  fi

  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "Server running with PID $pid on port $PORT."
    return 0
  fi

  pid="$(find_pids_by_port)"
  if [ -n "$pid" ]; then
    echo "Port $PORT is in use by PID(s): $(echo "$pid" | tr '\n' ' ')."
  else
    echo "Server not running."
  fi
}

logs_server() {
  if [ ! -f "$LOG_FILE" ]; then
    echo "Log file not found: $LOG_FILE"
    exit 1
  fi
  tail -f "$LOG_FILE"
}

usage() {
  echo "Usage: ./runserver.sh {start|stop|restart|status|logs}"
}

case "${1:-start}" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    start_server
    ;;
  status)
    status_server
    ;;
  logs)
    logs_server
    ;;
  *)
    usage
    exit 1
    ;;
esac
