#!/usr/bin/env bash
# run.sh — start both llama.cpp model server and FastAPI backend server.
#
# Usage:
#   ./run.sh          # start both servers
#   ./run.sh --stop   # stop both servers
#   ./run.sh --status # check status of both servers
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

case "${1:-start}" in
  --stop|stop)
    echo "Stopping API server..."
    ./runserver.sh stop || true
    echo "Stopping model server..."
    ./run_model_server.sh --stop || true
    exit 0
    ;;
  --status|status)
    echo "=== Model Server Status ==="
    ./run_model_server.sh --status || true
    echo
    echo "=== API Server Status ==="
    ./runserver.sh status || true
    exit 0
    ;;
  start|"")
    echo "=== Starting Model Server ==="
    ./run_model_server.sh --bg

    echo
    echo "=== Starting API Server ==="
    ./runserver.sh start

    echo
    echo "Both services started successfully."
    echo "  Check API health   : curl -s http://localhost:8000/health"
    echo "  Check Model health : curl -s http://localhost:8081/health"
    echo "  Stop both          : ./run.sh --stop"
    ;;
  *)
    echo "Usage: ./run.sh [start|stop|--stop|status|--status]"
    exit 1
    ;;
esac
