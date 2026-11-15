#!/usr/bin/env bash
# docintel - set up (first time only) and start the web app, then open the browser.
set -e
cd "$(dirname "$0")"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed: https://www.python.org/downloads/ (macOS: brew install python)"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Setting up docintel for the first time - this takes a minute or two..."
  "$PY" -m venv .venv || { echo "Could not create the Python environment (Ubuntu/Debian: sudo apt install python3-venv)"; exit 1; }
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .

if ! command -v tesseract >/dev/null 2>&1; then
  echo
  echo "Note: Tesseract OCR was not found - scanned pages and photos will be marked 'Needs OCR'."
  echo "Install it (macOS: brew install tesseract, Ubuntu/Debian: sudo apt install tesseract-ocr) to read them."
  echo
fi

PORT="${PORT:-8000}"
echo
echo "docintel is starting at http://localhost:$PORT  - press Ctrl+C to stop it."
echo
if [ -z "$NO_BROWSER" ]; then
  ( sleep 5
    if command -v open >/dev/null 2>&1; then open "http://localhost:$PORT"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:$PORT" >/dev/null 2>&1
    fi ) &
fi
exec .venv/bin/python -m docintel serve --port "$PORT"
