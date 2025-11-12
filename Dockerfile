# Cloud Run–friendly Whisper API
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV WHISPER_DIR=/app/whisper.cpp
ENV MODELS_DIR=/app/models
ENV PORT=8080
# Default model path (can override with -e WHISPER_MODEL=...)
ENV WHISPER_MODEL=${MODELS_DIR}/ggml-base.en.bin
# Optional: model URL to fetch at container start if model file is missing
ENV WHISPER_MODEL_URL=https://ggml.ggerganov.com/whisper/models/ggml-base.en.bin

# System deps (ffmpeg for decoding, build tools for whisper.cpp, python for API)
RUN apt-get update && apt-get install -y \
    git build-essential ffmpeg wget ca-certificates python3 python3-pip curl \
 && rm -rf /var/lib/apt/lists/*

# Build whisper.cpp (CPU build for Cloud Run)
RUN git clone --depth=1 https://github.com/ggerganov/whisper.cpp.git ${WHISPER_DIR} \
 && make -C ${WHISPER_DIR} -j

# App files
WORKDIR /app
COPY server.py /app/server.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
 && pip3 install --no-cache-dir fastapi uvicorn[standard] python-multipart

# Run as non-root for Cloud Run best practice
RUN useradd -m appuser \
 && mkdir -p ${MODELS_DIR} /tmp \
 && chown -R appuser:appuser /app /tmp
USER appuser

# Cloud Run uses $PORT
EXPOSE 8080
CMD ["/app/entrypoint.sh"]
