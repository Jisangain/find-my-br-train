#!/bin/bash

cd find-my-br-train || echo "Directory not found"

PIDS=$(ps aux | grep '[g]unicorn.*main:app' | awk '{print $2}')
if [ -n "$PIDS" ]; then
    echo "Killing Gunicorn PIDs: $PIDS"
    kill $PIDS
    sleep 3
else
    echo "No running gunicorn process found."
fi

# Reset and pull latest code
git reset --hard origin/master
git pull origin master

# Activate virtual environment
source venv/bin/activate

# Ensure port 8000 is free
PORT_IN_USE=$(lsof -i :8000 | awk 'NR>1 {print $2}' | sort -u)
if [ -n "$PORT_IN_USE" ]; then
    echo "Port 8000 is in use by PID(s): $PORT_IN_USE, killing..."
    kill $PORT_IN_USE
    sleep 2
fi

echo "Starting Gunicorn..."
nohup gunicorn main:app -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000 > output.log 2>&1 &

echo "FastAPI app restarted."