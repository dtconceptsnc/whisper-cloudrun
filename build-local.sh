#!/usr/bin/env bash
set -euo pipefail

# Quick local build and test script

IMAGE_NAME="whisper-cloudrun"
PORT="${PORT:-8080}"

echo "Building Docker image..."
docker build --platform linux/amd64 -t "$IMAGE_NAME" .

echo ""
echo "Build complete! Run with:"
echo ""
echo "  # Run with default model (base.en)"
echo "  docker run --rm -p $PORT:8080 $IMAGE_NAME"
echo ""
echo "  # Run with custom model"
echo "  docker run --rm -p $PORT:8080 \\"
echo "    -e WHISPER_MODEL_URL=https://ggml.ggerganov.com/whisper/models/ggml-small.en.bin \\"
echo "    $IMAGE_NAME"
echo ""
echo "Then test at: http://localhost:$PORT/healthz"
