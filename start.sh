#!/bin/bash

cleanup() {
    echo "Stopping services..."
    pkill -P $$
}

trap cleanup SIGINT

PORT=8000
EXISTING_PID=$(lsof -t -i:$PORT)
if [ -n "$EXISTING_PID" ]; then
    echo "Killing existing process on port $PORT"
    kill -9 $EXISTING_PID
    sleep 1
fi

echo "Starting Backend"
export PYTHONPATH=$(pwd)
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi
"$PYTHON" run_web.py &

echo "Starting Frontend"
cd client
npm run dev &

echo "Services started"
wait
