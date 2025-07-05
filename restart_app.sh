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

bash background_run.sh