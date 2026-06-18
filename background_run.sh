# Activate virtual environment
cd find-my-br-train || echo "Directory not found"
source venv/bin/activate

# Ensure port 8000 is free
PORT_IN_USE=$(lsof -i :8000 | awk 'NR>1 {print $2}' | sort -u)
if [ -n "$PORT_IN_USE" ]; then
    echo "Port 8000 is in use by PID(s): $PORT_IN_USE, killing..."
    kill $PORT_IN_USE
    sleep 2
fi
pip install -r requirements.txt
echo "Starting Gunicorn..."
export PYTHONUNBUFFERED=1
export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-find-my-br-train}"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://127.0.0.1:4317}"
export OTEL_EXPORTER_OTLP_PROTOCOL="${OTEL_EXPORTER_OTLP_PROTOCOL:-grpc}"
nohup gunicorn main:app -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000 > output.log 2>&1 &

echo "FastAPI app restarted."