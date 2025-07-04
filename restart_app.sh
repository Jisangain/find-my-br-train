#!/bin/bash

cd /path/to/your/fastapi || { echo "Directory not found"; exit 1; }

# Kill existing Gunicorn process
PID=$(ps aux | grep '[g]unicorn.*main:app' | awk '{print $2}')
sleep 2
if [ -n "$PID" ]; then
    echo "Killing process $PID"
    kill "$PID"
    sleep 2
else
    echo "No running gunicorn process found."
fi

# Reset and pull latest changes
git reset --hard origin/master
git pull origin master

# Activate venv
source venv/bin/activate

# Restart Gunicorn with Uvicorn worker
nohup gunicorn main:app -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000 > output.log 2>&1 &
echo "FastAPI app restarted."
