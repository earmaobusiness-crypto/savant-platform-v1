#!/usr/bin/env bash
# Always start Room 3 / Savant with the project venv (avoids missing groq/alpaca-py).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Missing .venv — create it and: .venv/bin/pip install -r requirements.txt"
  exit 1
fi
exec "$ROOT/.venv/bin/python" -m streamlit run app.py "$@"
