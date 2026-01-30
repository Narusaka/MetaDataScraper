#!/bin/bash

# Function to kill all background processes on exit
cleanup() {
    echo "Stopping services..."
    # Kill all child processes of this shell
    pkill -P $$
}

# Trap SIGINT (Ctrl+C) and call cleanup
trap cleanup SIGINT

echo "Starting Backend (Python)..."
# Using python3 if available, or fallback to python. 
# Assuming the user's environment is already active or 'python' points to the right one.
echo "Running python run_web.py"
python run_web.py &

echo "Starting Frontend (npm)..."
cd client
echo "Running npm run dev"
npm run dev &

# Wait for all background processes
echo "Services started. Press Ctrl+C to stop."
wait
