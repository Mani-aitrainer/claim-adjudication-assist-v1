#!/bin/sh
set -e

exec uvicorn app.main:app \
    --app-dir src \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-2}"
