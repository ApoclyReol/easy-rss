#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
cd "$SCRIPT_DIR"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "未找到 Python，请先安装 Python 3。"
  exit 1
fi

if [ ! -d ".venv" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv
  else
    "$PYTHON_BIN" -m venv .venv
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -r requirements.txt
else
  .venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python -m streamlit run app/streamlit_app.py
