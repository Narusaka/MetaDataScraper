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
python run_web.py &

echo "Starting Frontend"
cd client
npm run dev &

echo "Services started"
wait
