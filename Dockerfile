# GPU-only whisperX API for Cloud Run (CUDA 12.4 + cuDNN 9.x)
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PORT=8080

# WhisperX / CTranslate2 config - runtime is GPU-only
ENV WHISPERX_MODEL=Systran/faster-whisper-medium.en
ENV WHISPERX_DEVICE=cuda
ENV WHISPERX_COMPUTE_TYPE=float16
ENV WHISPERX_BATCH_SIZE=16
ENV WHISPERX_CACHE=/app/.cache/whisperx
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
ENV HF_HOME=/app/.cache/huggingface
ENV PIP_ROOT_USER_ACTION=ignore
ENV MPLBACKEND=Agg

# CTranslate2 – force GPU backend at runtime
ENV CT2_USE_EXPERIMENTAL_PACKED_GEMM=1
ENV CT2_FORCE_GPU=1

# System deps
RUN apt-get update && apt-get install -y \
    git build-essential ffmpeg pkg-config \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libswresample-dev libswscale-dev \
    wget ca-certificates python3 python3-pip python3-dev curl libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

# Torch wheel index for CUDA 12.4
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124
ARG FASTER_WHISPER_VERSION=1.1.1
ARG HF_TOKEN
ARG ALIGN_LANGS="en"

ENV ALIGN_LANGS=${ALIGN_LANGS}

# Require HF_TOKEN at build time (for gated pyannote models)
RUN test -n "$HF_TOKEN" || (echo "HF_TOKEN is required at build time. Pass --build-arg HF_TOKEN=YOUR_TOKEN" && exit 1)

# Python deps (GPU PyTorch + whisperX + diarization)
RUN python3 -m pip install --no-cache-dir --upgrade pip \
 && python3 -m pip install --no-cache-dir numpy==2.0.2 \
 && python3 -m pip install --no-cache-dir \
    torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url ${TORCH_INDEX_URL} \
 && python3 -m pip install --no-cache-dir \
    fastapi uvicorn[standard] python-multipart requests transformers==4.48.1 nltk huggingface_hub \
 && python3 -m pip install --no-cache-dir \
    whisperx==3.4.2 --no-deps \
 && python3 -m pip install --no-cache-dir \
    faster-whisper==${FASTER_WHISPER_VERSION} pandas pyannote.audio==3.3.2 \
 && python3 -m pip install --no-cache-dir \
    "matplotlib<4"

# ---- Build-time pre-download of ASR + diarization + align models (CPU only, no CT2 runtime) ----
RUN HF_TOKEN="$HF_TOKEN" python3 - << 'EOF'
import os
from huggingface_hub import snapshot_download
from whisperx.diarize import DiarizationPipeline
import whisperx

cache_root = os.environ.get("WHISPERX_CACHE", "/app/.cache/whisperx")
model_id   = os.environ.get("WHISPERX_MODEL", "Systran/faster-whisper-tiny")
hf_token   = os.environ.get("HF_TOKEN")
langs      = [lang.strip() for lang in os.environ.get("ALIGN_LANGS", "en").split(",") if lang.strip()]

os.makedirs(cache_root, exist_ok=True)

# 1) ASR model snapshot
print(f">>> Snapshotting ASR model repo '{model_id}' into cache...")
snapshot_download(
    repo_id=model_id,
    local_dir=os.path.join(cache_root, model_id.replace('/', os.sep)),
    local_dir_use_symlinks=False,
    token=hf_token,
)
print(">>> ASR repo snapshot complete.")

# 2) Diarization model snapshot
diarization_repo = "pyannote/speaker-diarization-3.1"
print(f">>> Snapshotting diarization repo '{diarization_repo}' into cache...")
snapshot_download(
    repo_id=diarization_repo,
    local_dir=os.path.join(cache_root, diarization_repo.replace('/', os.sep)),
    local_dir_use_symlinks=False,
    token=hf_token,
)
print(">>> Diarization repo snapshot complete.")

# 3) WhisperX Alignment models
for lang in langs:
    print(f">>> Downloading alignment model for language '{lang}' into {cache_root} ...")
    whisperx.load_align_model(
        language_code=lang,
        device="cpu",
        model_dir=cache_root,
    )

print(">>> Build-time pre-download complete.")
EOF

# ---- Runtime GPU check: FAIL if no CUDA in Cloud Run ----
RUN mkdir -p /app \
 && python3 - << 'EOF'
import textwrap, os

code = textwrap.dedent("""
import torch, sys

print(">>> Runtime GPU check: verifying CUDA availability...")
if not torch.cuda.is_available():
    print("FATAL: CUDA is NOT available inside the container (GPU-only service).", file=sys.stderr)
    sys.exit(1)

num = torch.cuda.device_count()
print(f">>> CUDA is available. Visible GPU count: {num}")
sys.exit(0)
""")

with open("/app/check_gpu.py", "w") as f:
    f.write(code)
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

EXPOSE 8080

# 1) Check GPU at runtime → crash if no CUDA
# 2) Start your FastAPI/uvicorn entrypoint
CMD ["bash", "-lc", "python3 /app/check_gpu.py && /app/entrypoint.sh"]
