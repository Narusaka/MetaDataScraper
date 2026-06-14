#!/bin/bash
set -e

cleanup() {
    echo "Stopping services..."
    if [ -n "${BACKEND_PID:-}" ]; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "${FRONTEND_PID:-}" ]; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    pkill -P $$ || true
}

wait_for_http() {
    local name="$1"
    local url="$2"
    local pid="$3"
    local attempts="${4:-30}"

    echo "Waiting for $name at $url"
    for _ in $(seq 1 "$attempts"); do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" || EXIT_CODE=$?
            echo "Error: $name process stopped before it became ready."
            exit "${EXIT_CODE:-1}"
        fi
        if curl -fsS "$url" >/dev/null 2>&1; then
            echo "$name ready"
            return 0
        fi
        sleep 1
    done

    echo "Error: $name did not become ready within ${attempts}s: $url"
    exit 1
}

trap cleanup EXIT SIGINT SIGTERM

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if ! command -v npm >/dev/null 2>&1; then
    echo "Error: npm is not installed or not in PATH."
    exit 1
fi

if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    echo "Creating Python virtual environment"
    python3 -m venv .venv
    PYTHON=".venv/bin/python"
else
    echo "Error: python3 is not installed or not in PATH."
    exit 1
fi

echo "Installing Backend Dependencies"
"$PYTHON" -m pip install -q -r requirements.txt

if [ ! -d "client/node_modules" ]; then
    echo "Installing Frontend Dependencies"
    (cd client && npm install)
fi

PORT="${WEB_PORT:-8000}"
EXISTING_PID=$(lsof -t -i:$PORT || true)
if [ -n "$EXISTING_PID" ]; then
    echo "Killing existing process on port $PORT"
    kill -9 $EXISTING_PID || true
    sleep 1
fi

echo "Starting Backend"
export PYTHONPATH="$ROOT_DIR"
"$PYTHON" run_web.py &
BACKEND_PID=$!

echo "Starting Frontend"
cd client
npm run dev &
FRONTEND_PID=$!

wait_for_http "Backend" "http://127.0.0.1:${PORT}/api/status" "$BACKEND_PID" 45
wait_for_http "Frontend" "http://127.0.0.1:5173/" "$FRONTEND_PID" 45

echo "Services ready"
echo "Frontend: http://127.0.0.1:5173/"
echo "Backend:  http://127.0.0.1:${PORT}"
while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        wait "$BACKEND_PID" || EXIT_CODE=$?
        echo "Backend stopped"
        exit "${EXIT_CODE:-1}"
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        wait "$FRONTEND_PID" || EXIT_CODE=$?
        echo "Frontend stopped"
        exit "${EXIT_CODE:-1}"
    fi
    sleep 1
done
