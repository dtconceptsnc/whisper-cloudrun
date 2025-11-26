#!/usr/bin/env bash
set -euo pipefail

# Quick local build and test script

IMAGE_NAME="whisperx-cloudrun"
PORT="${PORT:-8080}"

echo "Building Docker image (requires HF_TOKEN for diarization)..."
if [ -z "${HF_TOKEN:-}" ]; then
  echo "Error: HF_TOKEN must be set for build (needed to pre-download diarization model)." >&2
  exit 1
fi
docker build --platform linux/amd64 --build-arg HF_TOKEN="$HF_TOKEN" -t "$IMAGE_NAME" .

echo ""
echo "Build complete! Run with:"
echo ""
echo "  # Run with default model (large-v3) on GPU"
echo "  docker run --rm --gpus all -p $PORT:8080 $IMAGE_NAME"
echo ""
echo "  # Run with custom model"
echo "  docker run --rm --gpus all -p $PORT:8080 \\"
echo "    -e WHISPERX_MODEL=medium.en \\"
echo "    $IMAGE_NAME"
echo ""
echo "Then test at: http://localhost:$PORT/healthz"
