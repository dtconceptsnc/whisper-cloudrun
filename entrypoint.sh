#!/usr/bin/env bash
set -euo pipefail

# Ensure model exists (download on first run if missing)
if [ ! -f "${WHISPER_MODEL}" ]; then
  echo "Model not found at ${WHISPER_MODEL}"
  if [ -n "${WHISPER_MODEL_URL:-}" ]; then
    echo "Downloading model from ${WHISPER_MODEL_URL}..."
    mkdir -p "$(dirname "${WHISPER_MODEL}")"
    wget --progress=bar:force -O "${WHISPER_MODEL}" "${WHISPER_MODEL_URL}" || {
      echo "Failed to download model"
      exit 1
    }
    echo "Model downloaded to ${WHISPER_MODEL}"
  else
    echo "WHISPER_MODEL_URL not set and model missing. Exiting."
    exit 1
  fi
fi

# Start API (bind to $PORT as required by Cloud Run)
exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8080}"
