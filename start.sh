#!/usr/bin/env bash
# Claw / Jarvis — one-click starter for macOS and Linux
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install it from https://www.python.org/downloads/ first."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f .venv/.deps_installed ]; then
  echo "Installing Jarvis components, one moment..."
  pip install -r requirements.txt || exit 1
  touch .venv/.deps_installed
fi

echo
echo "  =========================================="
echo "   Your Jarvis is starting..."
echo "   It will open in your browser automatically."
echo "   Press Ctrl+C to stop Jarvis."
echo "  =========================================="
echo

(sleep 4 && (open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 2>/dev/null)) &
python run.py
