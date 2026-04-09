#!/bin/bash
# start.sh: Run both Backend and Worker in one container for Free Tier compatibility

echo "Starting Celery Worker..."
celery -A app.tasks worker --loglevel=info &

echo "Starting FastAPI Backend..."
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
