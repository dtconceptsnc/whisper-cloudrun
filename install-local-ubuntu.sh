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

# Handle cuDNN version conflict: PyTorch 2.5+ needs cuDNN 9, pyannote needs cuDNN 8
# Install cuDNN 8 in venv (for pyannote), and cuDNN 9 in separate location (for PyTorch)
if [[ -x "$(command -v nvidia-smi)" && -z "${FORCE_CPU:-}" ]]; then
  echo "Setting up cuDNN libraries for GPU support..."

  # PyTorch installs cuDNN 9 by default; downgrade to cuDNN 8 for pyannote
  pip install --no-cache-dir nvidia-cudnn-cu12==8.9.7.29

  # Install cuDNN 9 to a separate location for PyTorch
  CUDNN9_DIR="${PWD}/.cudnn9"
  mkdir -p "${CUDNN9_DIR}"
  pip install --no-cache-dir nvidia-cudnn-cu12==9.1.0.70 --target "${CUDNN9_DIR}"

  # Reinstall cuDNN 8 in venv (pip install above overwrote it)
  pip install --no-cache-dir nvidia-cudnn-cu12==8.9.7.29
fi

cat <<'EOF'

✅ Local install complete.

Next steps:
  source .venv/bin/activate
  export HF_TOKEN=...   # required for diarization (pyannote) downloads

  # For GPU, set LD_LIBRARY_PATH to include both cuDNN versions:
  export LD_LIBRARY_PATH="${PWD}/.cudnn9/nvidia/cudnn/lib:${PWD}/.venv/lib/python3.12/site-packages/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"

  uvicorn server:app --host 0.0.0.0 --port 8080

  # CPU fallback (no cuDNN needed):
  #   export WHISPERX_DEVICE=cpu WHISPERX_COMPUTE_TYPE=float32 WHISPERX_BATCH_SIZE=2
  #   uvicorn server:app --host 0.0.0.0 --port 8080

EOF
