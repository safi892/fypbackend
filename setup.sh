#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Python 3.11+ is required but was not found in PATH."
  exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    print("Python 3.11+ is required.", file=sys.stderr)
    sys.exit(1)
PY

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  "$PYTHON" -m venv .venv
fi

if [ -x ".venv/bin/python" ]; then
  VENV_PY=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  VENV_PY=".venv/Scripts/python.exe"
else
  echo "Virtual environment python not found."
  exit 1
fi

"$VENV_PY" -m pip install --upgrade pip

mapfile -t DEPS < <("$VENV_PY" - <<'PY'
from __future__ import annotations
import pathlib
import sys
import tomllib

path = pathlib.Path("pyproject.toml")
if not path.exists():
    print("pyproject.toml not found.", file=sys.stderr)
    sys.exit(1)

data = tomllib.loads(path.read_text())
deps = data.get("project", {}).get("dependencies", []) or []
for dep in deps:
    print(dep)
PY
)

if [ ${#DEPS[@]} -gt 0 ]; then
  echo "Installing dependencies..."
  "$VENV_PY" -m pip install "${DEPS[@]}"
else
  echo "No dependencies found in pyproject.toml."
fi

MODEL_DIR="$ROOT/codet5_commenst_expla/checkpoint_best"
MODEL_ZIP="$ROOT/codet5_commenst_expla.zip"

if [ ! -d "$MODEL_DIR" ]; then
  if [ -f "$MODEL_ZIP" ]; then
    echo "Extracting model from codet5_commenst_expla.zip..."
    if command -v unzip >/dev/null 2>&1; then
      unzip -o "$MODEL_ZIP" -d "$ROOT" >/dev/null
    else
      "$VENV_PY" - <<'PY'
import pathlib
import zipfile

zip_path = pathlib.Path("codet5_commenst_expla.zip")
with zipfile.ZipFile(zip_path, "r") as zf:
    zf.extractall(pathlib.Path("."))
PY
    fi
  fi
fi

missing_files=()
for name in config.json tokenizer.json model.safetensors; do
  if [ ! -f "$MODEL_DIR/$name" ]; then
    missing_files+=("$name")
  fi
done

if [ ${#missing_files[@]} -gt 0 ]; then
  echo "Model files missing in $MODEL_DIR: ${missing_files[*]}"
  echo "Make sure the model folder is present or unzip codet5_commenst_expla.zip."
else
  echo "Model files found in $MODEL_DIR."
fi

mkdir -p "$ROOT/logs"

echo "Setup complete."
echo "Next: ./runserver.sh start"
