#!/usr/bin/env bash
set -euo pipefail

# Start API (bind to $PORT as required by Cloud Run)
exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8080}"
