# GPU-only whisperX API for Cloud Run
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PORT=8080
ENV WHISPERX_MODEL=large-v3
ENV WHISPERX_DEVICE=cuda
ENV WHISPERX_COMPUTE_TYPE=float16
ENV WHISPERX_BATCH_SIZE=16
ENV WHISPERX_CACHE=/app/.cache/whisperx
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
ENV HF_HOME=/app/.cache/huggingface
ENV PIP_ROOT_USER_ACTION=ignore
ENV PIP_CONSTRAINT=/tmp/pip-constraints.txt

# System deps
RUN apt-get update && apt-get install -y \
    git build-essential ffmpeg pkg-config \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libswresample-dev libswscale-dev \
    wget ca-certificates python3 python3-pip python3-dev curl libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

# Torch source (override TORCH_INDEX_URL for CPU builds)
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu121
ARG FASTER_WHISPER_VERSION=1.1.1
ARG HF_TOKEN

ENV HF_TOKEN=${HF_TOKEN}

# Require HF_TOKEN at build time for gated pyannote diarization downloads
RUN test -n "$HF_TOKEN" || (echo "HF_TOKEN is required at build time. Pass --build-arg HF_TOKEN=YOUR_TOKEN" && exit 1)

# Python deps (GPU PyTorch + whisperX)
RUN echo "numpy<2" > ${PIP_CONSTRAINT} \
 && python3 -m pip install --no-cache-dir --upgrade pip \
 && python3 -m pip install --no-cache-dir -c ${PIP_CONSTRAINT} numpy==1.26.4 \
 && python3 -m pip install --no-cache-dir -c ${PIP_CONSTRAINT} \
    torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 --index-url ${TORCH_INDEX_URL} \
 && python3 -m pip install --no-cache-dir -c ${PIP_CONSTRAINT} \
    fastapi uvicorn[standard] python-multipart requests transformers==4.39.3 nltk \
 && python3 -m pip install --no-cache-dir -c ${PIP_CONSTRAINT} \
    whisperx==3.4.2 --no-deps \
 && python3 -m pip install --no-cache-dir -c ${PIP_CONSTRAINT} \
    faster-whisper==${FASTER_WHISPER_VERSION} pandas pyannote.audio==3.1.1 \
 && python3 -m pip install --no-cache-dir -c ${PIP_CONSTRAINT} --upgrade --force-reinstall numpy==1.26.4 \
 && python3 -c "import whisperx; whisperx.load_model('large-v3', device='cpu', compute_type='float32', download_root='/app/.cache/whisperx')" \
 && python3 - << 'EOF'

 
from whisperx.diarize import DiarizationPipeline
import os

hf_token = os.environ.get("HF_TOKEN", None)
pipeline = DiarizationPipeline(
    model_name="pyannote/speaker-diarization-3.1",
    use_auth_token=hf_token,
    device="cpu",
)
# Constructor call is enough to download weights
EOF

# App files
WORKDIR /app
COPY server.py /app/server.py
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh \
 && useradd -m appuser \
 && mkdir -p ${WHISPERX_CACHE} ${TRANSFORMERS_CACHE} /tmp \
 && chown -R appuser:appuser /app /tmp ${WHISPERX_CACHE} ${TRANSFORMERS_CACHE}
USER appuser

# Cloud Run uses $PORT
EXPOSE 8080
CMD ["/app/entrypoint.sh"]
