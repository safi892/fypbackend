#!/usr/bin/env bash
# run_model_server.sh — start the llama.cpp server that backs MODEL_BACKEND=qwen_gguf.
#
# Problem solved: the API talks to a separate inference process, and a teammate
# should not have to know where the weights live or which port avoids a clash.
# Everything is resolved from this project, so a checkout plus the models/
# directory is all that is needed.
#
# Usage:
#   ./run_model_server.sh          # start in the foreground
#   ./run_model_server.sh --bg     # start in the background, log to logs/
#   ./run_model_server.sh --stop   # stop a running instance
#   ./run_model_server.sh --status # say whether one is already running
#
# Port 8081, not llama.cpp's default 8080: the FastAPI app listens on 8080, and
# the two silently fighting over the socket is a confusing way to find out.
set -euo pipefail

cd "$(dirname "$0")"

MODEL="${LLAMA_MODEL_PATH:-models/gguf/qwen-cpp-review-q4_k_m.gguf}"
PORT="${LLAMA_PORT:-8081}"
THREADS="${LLAMA_THREADS:-8}"
CONTEXT="${LLAMA_CONTEXT:-4096}"
LOG="logs/llama-server.log"

# Is one already serving on this port? Starting a second is the common mistake,
# and llama.cpp reports it as "couldn't bind HTTP server socket", which says
# what failed but not that the thing you wanted is already true.
already_serving() {
  curl -s --max-time 2 "http://127.0.0.1:${PORT}/health" 2>/dev/null | grep -q '"status"'
}

# `|| true` is load-bearing: lsof exits 1 when nothing holds the port, and with
# `set -eo pipefail` that would kill the script exactly when the answer is the
# unremarkable "nothing is running".
port_owner() {
  lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1 " (pid " $2 ")"}' || true
}

if [ "${1:-}" = "--stop" ]; then
  pkill -f "llama-server .*${MODEL##*/}" && echo "stopped" || echo "nothing running"
  exit 0
fi

if [ "${1:-}" = "--status" ]; then
  if already_serving; then
    echo "running: $(port_owner) is serving on port ${PORT}"
  else
    owner="$(port_owner)"
    if [ -n "$owner" ]; then
      echo "port ${PORT} held by $owner, but it is not answering /health"
    else
      echo "not running"
    fi
  fi
  exit 0
fi

if already_serving; then
  echo
  echo "Already running: $(port_owner) is serving on port ${PORT}."
  echo "Nothing to do - the API can use it as-is."
  echo
  echo "  restart:  ./run_model_server.sh --stop && ./run_model_server.sh --bg"
  echo "  check  :  curl -s localhost:8080/ready"
  exit 0
fi

owner="$(port_owner)"
if [ -n "$owner" ]; then
  echo "Port ${PORT} is held by $owner, which is not llama-server." >&2
  echo "Stop it, or set LLAMA_PORT and LLAMA_SERVER_URL to a free port." >&2
  exit 1
fi

if ! command -v llama-server >/dev/null 2>&1; then
  echo "llama-server not found. Install llama.cpp:" >&2
  echo "  macOS:  brew install llama.cpp" >&2
  echo "  other:  https://github.com/ggml-org/llama.cpp" >&2
  exit 1
fi

if [ ! -f "$MODEL" ]; then
  echo "Model not found: $MODEL" >&2
  echo "Expected the GGUF under models/gguf/. Set LLAMA_MODEL_PATH to override." >&2
  exit 1
fi

echo "model  : $MODEL ($(du -h "$MODEL" | cut -f1))"
echo "port   : $PORT"
echo "threads: $THREADS"

if [ "${1:-}" = "--bg" ]; then
  mkdir -p logs
  nohup llama-server -m "$MODEL" --port "$PORT" -c "$CONTEXT" -t "$THREADS" \
    > "$LOG" 2>&1 &
  echo "started in the background, logging to $LOG"
  printf "waiting for the model to load"
  until curl -s "http://127.0.0.1:${PORT}/health" 2>/dev/null | grep -q '"status":"ok"'; do
    printf "."
    sleep 2
  done
  echo " ready"
else
  exec llama-server -m "$MODEL" --port "$PORT" -c "$CONTEXT" -t "$THREADS"
fi
