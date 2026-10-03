#!/usr/bin/env bash
# runserver.sh — run / manage / test the C++ code-review backend.
#
# Problem solved: one script to start, stop, inspect and test the FastAPI
# server, and to run the linters/type-checker/tests. Why it prefers `uv` (the
# tool that owns uv.lock) but falls back to a local `.venv`: the project is
# managed with uv, but the start path still launches uvicorn directly from the
# venv so we capture a clean PID for stop/restart.
#
# Usage: ./runserver.sh {start|stop|restart|status|logs|test|lint|typecheck}
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"


# `.env` holds the model paths, and only the Python app read it: this script
# computed its own default and looked for a file that is not there. Shell-safe
# lines only (KEY=VALUE), and the environment still wins so a one-off override
# on the command line keeps working.
if [ -f .env ]; then
  while IFS='=' read -r key value; do
    case "$key" in ''|'#'*) continue ;; esac
    key="${key%"${key##*[![:space:]]}"}"
    if [ -z "${!key:-}" ]; then export "$key=$value"; fi
  done < .env
fi

PORT="${PORT:-8000}"
MODEL_DIR="$ROOT/codet5_commenst_expla/checkpoint_best"

# Only the CodeT5 backend reads these, and it is no longer the default. They are
# exported with `:-` so a value from .env or the caller is not overwritten by a
# path to a checkpoint this repository does not ship.
export MODEL_PATH="${MODEL_PATH:-$MODEL_DIR}"
export TOKENIZER_PATH="${TOKENIZER_PATH:-$MODEL_DIR}"

LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/server.log"
PID_FILE="$ROOT/.server.pid"


# --- helpers --------------------------------------------------------------- #
is_windows() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

# Print the python interpreter inside the project venv (uv-managed or manual).
venv_python() {
  if [ -x ".venv/bin/python" ]; then
    echo ".venv/bin/python"
  elif [ -x ".venv/Scripts/python.exe" ]; then
    echo ".venv/Scripts/python.exe"
  else
    echo ""
  fi
}

# Run a command via `uv run` when available, else via the venv python.
run_tool() {
  if command -v uv >/dev/null 2>&1; then
    uv run "$@"
  else
    local py
    py="$(venv_python)"
    [ -n "$py" ] || { echo "No uv and no .venv found. Run 'uv sync' first."; exit 1; }
    "$py" -m "$@"
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
  [ -z "$pid" ] && return 0
  if is_windows; then
    taskkill /PID "$pid" /F >/dev/null 2>&1 || true
  else
    kill "$pid" >/dev/null 2>&1 || true
  fi
}


# --- server lifecycle ------------------------------------------------------ #
start_server() {
  local venv_py
  venv_py="$(venv_python)"
  if [ -z "$venv_py" ]; then
    echo "Virtual environment not found. Run 'uv sync' first."
    exit 1
  fi

  mkdir -p "$LOG_DIR"

  # Only warn about the CodeT5 checkpoint when CodeT5 is the backend actually
  # selected. The default is qwen_gguf, which never loads that directory, so the
  # old unconditional warning said /analyze would return 503 while /analyze was
  # working - the kind of message that gets believed and then ignored.
  if [ "${MODEL_BACKEND:-qwen_gguf}" = "codet5" ] && [ ! -d "$MODEL_DIR" ]; then
    echo "Warning: MODEL_BACKEND=codet5 but its checkpoint is not here: $MODEL_DIR"
    echo "/analyze will return 503 until it is, or set MODEL_BACKEND=qwen_gguf."
  fi

  local port_pids
  port_pids="$(find_pids_by_port)"
  if [ -n "$port_pids" ]; then
    echo "Port $PORT is in use by PID(s): $(echo "$port_pids" | tr '\n' ' ')"
    while IFS= read -r pid; do [ -n "$pid" ] && stop_pid "$pid"; done <<< "$port_pids"
  fi

  echo "Starting server on port $PORT..."
  # Launch uvicorn directly from the venv so $! is the real process PID.
  "$venv_py" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  echo "Server started (PID $(cat "$PID_FILE")). Logs: $LOG_FILE"
  echo "Health check: curl -s http://localhost:$PORT/health"
}

stop_server() {
  local pid=""
  [ -f "$PID_FILE" ] && pid="$(cat "$PID_FILE")"
  [ -z "$pid" ] && pid="$(find_pids_by_port)"

  if [ -z "$pid" ]; then
    echo "No server process found."
    return 0
  fi

  if [ -f "$PID_FILE" ]; then
    echo "Stopping server (PID $pid)..."
    stop_pid "$pid"
  else
    echo "Stopping server on port $PORT (PID(s): $(echo "$pid" | tr '\n' ' '))..."
    while IFS= read -r p; do [ -n "$p" ] && stop_pid "$p"; done <<< "$pid"
  fi
  rm -f "$PID_FILE"
}

status_server() {
  local pid=""
  [ -f "$PID_FILE" ] && pid="$(cat "$PID_FILE")"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "Server running (PID $pid) on port $PORT."
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
  [ -f "$LOG_FILE" ] || { echo "Log file not found: $LOG_FILE"; exit 1; }
  tail -f "$LOG_FILE"
}


# --- dev tasks ------------------------------------------------------------- #
run_tests() {
  echo "Running pytest..."
  run_tool pytest
}

run_lint() {
  echo "Running ruff..."
  run_tool ruff check app
  run_tool ruff format --check app
}

run_typecheck() {
  echo "Running mypy (strict)..."
  run_tool mypy app
}


# --- dispatch -------------------------------------------------------------- #
usage() {
  echo "Usage: ./runserver.sh {start|stop|restart|status|logs|test|lint|typecheck}"
}

case "${1:-start}" in
  start)   start_server ;;
  stop)    stop_server ;;
  restart) stop_server; start_server ;;
  status)  status_server ;;
  logs)    logs_server ;;
  test)    run_tests ;;
  lint)    run_lint ;;
  typecheck) run_typecheck ;;
  *)       usage; exit 1 ;;
esac
