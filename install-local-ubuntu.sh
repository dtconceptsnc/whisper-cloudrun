#!/usr/bin/env bash
set -euo pipefail

# Install whisperX API dependencies directly on Ubuntu (no Docker).
# Usage:
#   HF_TOKEN=... ./install-local-ubuntu.sh
#   SKIP_APT=1 TORCH_INDEX_URL=... ./install-local-ubuntu.sh  # if system deps already installed

if [[ -f /etc/os-release ]]; then
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" ]]; then
    echo "This script is intended for Ubuntu. Detected: ${ID:-unknown}" >&2
    exit 1
  fi
else
  echo "Cannot detect OS (missing /etc/os-release). Aborting." >&2
  exit 1
fi

SUDO="sudo"
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  SUDO=""
fi

if [[ "${SKIP_APT:-0}" != "1" ]]; then
  echo "Installing system dependencies via apt..."
  ${SUDO} apt-get update
  ${SUDO} apt-get install -y \
    python3 python3-venv python3-dev \
    build-essential ffmpeg pkg-config \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libswresample-dev libswscale-dev libsndfile1 \
    git curl
fi

PYTHON="${PYTHON:-python3}"
if ! command -v "${PYTHON}" >/dev/null 2>&1; then
  echo "Python executable '${PYTHON}' not found." >&2
  exit 1
fi

echo "Creating virtual environment (.venv)..."
${PYTHON} -m venv .venv
source .venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

# Decide whether to install GPU or CPU PyTorch wheels
TORCH_INDEX_URL="${TORCH_INDEX_URL:-}"
if [[ -z "${TORCH_INDEX_URL}" ]]; then
  if [[ -z "${FORCE_CPU:-}" && -x "$(command -v nvidia-smi)" ]]; then
    TORCH_INDEX_URL="https://download.pytorch.org/whl/cu124"
    echo "Detected NVIDIA GPU. Installing CUDA wheels from ${TORCH_INDEX_URL}"
  else
    TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"
    echo "Installing CPU wheels from ${TORCH_INDEX_URL}"
  fi
else
  echo "Using custom TORCH_INDEX_URL=${TORCH_INDEX_URL}"
fi

export PIP_EXTRA_INDEX_URL="${TORCH_INDEX_URL}"

WHISPERX_CACHE="${WHISPERX_CACHE:-${PWD}/.cache/whisperx}"
export WHISPERX_CACHE
mkdir -p "${WHISPERX_CACHE}"

echo "Installing Python dependencies from requirements.txt ..."
pip install --no-cache-dir -r requirements.txt

cat <<'EOF'

✅ Local install complete.

Next steps:
  source .venv/bin/activate
  export HF_TOKEN=...   # required for diarization (pyannote) downloads
  # GPU (default): WHISPERX_DEVICE=cuda WHISPERX_COMPUTE_TYPE=float16
  # CPU fallback:  export WHISPERX_DEVICE=cpu WHISPERX_COMPUTE_TYPE=float32 WHISPERX_BATCH_SIZE=2
  uvicorn server:app --host 0.0.0.0 --port 8080

EOF
