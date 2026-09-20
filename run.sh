#!/bin/bash

# Vecto Unified Launcher
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

export DEVELOPER_DIR="/Library/Developer/CommandLineTools"
export PATH="/opt/homebrew/bin:$PATH"
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"

echo "=============================================="
echo " Starting Vecto Studio (VectoAI)..."
echo "=============================================="

# Cleanup on exit
cleanup() {
  echo ""
  echo "Shutting down Vecto services..."
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Start Backend
echo "-> Starting Backend on http://127.0.0.1:8001 ..."
PYTHONPATH=. "$PROJECT_ROOT/backend/venv/bin/python3" -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 &
BACKEND_PID=$!

# Wait for backend
echo "-> Waiting for backend to be ready..."
for i in {1..30}; do
  if curl -s http://127.0.0.1:8001/docs >/dev/null 2>&1; then
    echo "-> Backend ready!"
    break
  fi
  sleep 0.5
done

# Open Browser
open http://localhost:5174 2>/dev/null || true

# Start Frontend
echo "-> Starting Frontend on http://localhost:5174 ..."
cd "$PROJECT_ROOT/frontend"
npm run dev
