#!/usr/bin/env bash
# setup.sh — bootstrap the C++ code-review backend.
#
# Problem solved: create the environment and ensure the model is present so the
# server can run. Why uv-first: the project ships `uv.lock` and the dev tools
# (ruff/mypy/pytest) live in `[dependency-groups].dev`, which `uv sync` installs
# in one shot. A pip fallback keeps it working where uv is absent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODEL_DIR="$ROOT/codet5_commenst_expla/checkpoint_best"
MODEL_ZIP="$ROOT/codet5_commenst_expla.zip"

# --- Python version check -------------------------------------------------- #
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Python 3.11+ is required but was not found in PATH."; exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    print("Python 3.11+ is required.", file=sys.stderr); sys.exit(1)
PY

# --- Install dependencies -------------------------------------------------- #
if command -v uv >/dev/null 2>&1; then
  echo "Using uv to create the environment and install dependencies (incl. dev)..."
  uv sync
  VENV_PY=".venv/bin/python"
  [ -x "$VENV_PY" ] || VENV_PY=".venv/Scripts/python.exe"
else
  echo "uv not found; falling back to a local venv + pip."
  if [ ! -d ".venv" ]; then
    "$PYTHON" -m venv .venv
  fi
  VENV_PY=".venv/bin/python"
  if is_windows 2>/dev/null; then VENV_PY=".venv/Scripts/python.exe"; fi
  "$VENV_PY" -m pip install --upgrade pip
  # Runtime dependencies only in the pip fallback (dev tools optional).
  "$VENV_PY" -m pip install fastapi uvicorn transformers torch tree-sitter tree-sitter-cpp \
    numpy huggingface_hub protobuf sentencepiece
fi

# --- Ensure model files ---------------------------------------------------- #
if [ -f "$ROOT/scripts/download_model.py" ] && [ ! -f "$MODEL_DIR/model.safetensors" ]; then
  echo "Model checkpoint missing. Downloading via scripts/download_model.py ..."
  if command -v uv >/dev/null 2>&1; then
    uv run python "$ROOT/scripts/download_model.py"
  else
    "$VENV_PY" "$ROOT/scripts/download_model.py"
  fi
elif [ ! -d "$MODEL_DIR" ] && [ -f "$MODEL_ZIP" ]; then
  echo "Extracting model from $MODEL_ZIP ..."
  if command -v unzip >/dev/null 2>&1; then
    unzip -o "$MODEL_ZIP" -d "$ROOT" >/dev/null
  else
    "$VENV_PY" - <<'PY'
import pathlib, zipfile
with zipfile.ZipFile("codet5_commenst_expla.zip") as zf:
    zf.extractall(pathlib.Path("."))
PY
  fi
fi

# --- Report ---------------------------------------------------------------- #
missing=()
for name in config.json tokenizer.json model.safetensors; do
  [ -f "$MODEL_DIR/$name" ] || missing+=("$name")
done

mkdir -p "$ROOT/logs"

if [ ${#missing[@]} -gt 0 ]; then
  echo "WARNING: model files missing in $MODEL_DIR: ${missing[*]}"
  echo "The server will start but /analyze returns 503 until these are present."
else
  echo "Model files found in $MODEL_DIR."
fi

echo ""
echo "Setup complete."
echo "Next: ./runserver.sh start   (or: ./runserver.sh test | lint | typecheck)"
