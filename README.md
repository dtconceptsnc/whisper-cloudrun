# Whisper Cloud Run API (GPU, whisperX)

A containerized Whisper API powered by [whisperX](https://github.com/m-bain/whisperX) on GPU, designed for deployment on Google Cloud Run (GPU) or any NVIDIA-enabled Docker environment.

## Features

- GPU-accelerated transcription/alignment using whisperX
- **Async job queue** - handles long-running transcriptions without timeout
- **Callback support** - integrates with n8n, webhooks, and automation tools
- WhisperX alignment for better timestamps; optional speaker diarization (requires HF token)
- Multi-language support and English translation task
- Accepts both file uploads and URLs
- Queue statistics and monitoring

## Quick Start

### Build and Run Locally

```bash
# Build the GPU Docker image (for Cloud Run GPU / NVIDIA hosts)
docker build --platform linux/amd64 -t whisperx-cloudrun .

# Run locally (requires NVIDIA runtime)
docker run --rm --gpus all -p 8080:8080 whisperx-cloudrun

# Optional CPU-only build on ARM Macs (slow, for smoke tests)
docker build --no-cache --platform linux/arm64 \
  --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu \
  -t whisperx-cloudrun .
docker run --rm -p 8080:8080 \
  -e WHISPERX_DEVICE=cpu -e WHISPERX_COMPUTE_TYPE=float32 \
  -e WHISPERX_BATCH_SIZE=2 \
  whisperx-cloudrun
```

### Run Locally Without Docker (Ubuntu)

```bash
chmod +x install-local-ubuntu.sh
HF_TOKEN=your_hf_token ./install-local-ubuntu.sh
source .venv/bin/activate

# GPU (default)
uvicorn server:app --host 0.0.0.0 --port 8080

# CPU fallback
export WHISPERX_DEVICE=cpu WHISPERX_COMPUTE_TYPE=float32 WHISPERX_BATCH_SIZE=2
uvicorn server:app --host 0.0.0.0 --port 8080
```

Notes:
- Requires Ubuntu 22.04+ with Python 3.8+ and optionally NVIDIA drivers. The script installs system deps via `apt` unless `SKIP_APT=1`.
- CUDA wheels default to `cu124`; set `TORCH_INDEX_URL` to match your installed CUDA or force CPU with `FORCE_CPU=1`.
- `HF_TOKEN` is required to download the diarization model (`pyannote/speaker-diarization-3.1`) if `diarize=true`.

### Run with Custom Model

```bash
docker run --rm --gpus all -p 8080:8080 \
  -e WHISPERX_MODEL=large-v3 \
  whisperx-cloudrun
```

Common model names: `large-v3` (default, multilingual), `large-v2`, `medium.en` (English-only, faster).

## API Usage

### Health Check

```bash
curl http://localhost:8080/healthz
```

Response:
```json
{"ok": true}
```

### Async Transcription (Recommended for Cloud Run)

The async API prevents timeout issues on long audio files and supports webhooks.

**1. Start a transcription job:**

```bash
curl -X POST http://localhost:8080/transcribe/start \
  -F "url=https://example.com/audio.mp3"
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Job queued for processing"
}
```

**2. Poll for results:**

```bash
curl http://localhost:8080/transcribe/status/550e8400-e29b-41d4-a716-446655440000
```

Response (queued/running):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "result": null,
  "created_at": 1699564800.0,
  "updated_at": 1699564820.5
}
```

Response (completed):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "result": {
    "ok": true,
    "text": "Full transcription here...",
    "segments": [...],
    "language": "en",
    "warnings": null
  },
  "created_at": 1699564800.0,
  "updated_at": 1699564850.2
}
```

**3. Use callback URL (webhook):**

Instead of polling, provide a callback URL to receive results automatically:

```bash
curl -X POST http://localhost:8080/transcribe/start \
  -F "url=https://example.com/audio.mp3" \
  -F "callback_url=https://your-webhook.com/transcription-complete"
```

When the job completes, the service will POST to your callback URL:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "ok": true,
  "text": "Transcription...",
  "segments": [...],
  "language": "en"
}
```

### Synchronous Transcription (Legacy)

**⚠️ Warning:** This endpoint may timeout on Cloud Run for long audio files. Use `/transcribe/start` instead.

### Transcribe Audio File

**Basic transcription with file upload:**

```bash
curl -X POST http://localhost:8080/transcribe \
  -F "file=@/path/to/audio.mp3"
```

**Transcribe from URL:**

```bash
curl -X POST http://localhost:8080/transcribe \
  -F "url=https://example.com/audio.mp3"
```

**With speaker diarization disabled:**

```bash
curl -X POST http://localhost:8080/transcribe \
  -F "file=@audio.mp3" \
  -F "diarize=false"
```

**Specify language:**

```bash
curl -X POST http://localhost:8080/transcribe \
  -F "file=@audio.mp3" \
  -F "language=es"
```

**Translate to English:**

```bash
curl -X POST http://localhost:8080/transcribe \
  -F "file=@audio.mp3" \
  -F "language=es" \
  -F "translate=true"
```

**Full example with all options:**

```bash
curl -X POST http://localhost:8080/transcribe \
  -F "file=@meeting.wav" \
  -F "diarize=true" \
  -F "language=en" \
  -F "translate=false"
```

### Request Parameters

#### Async API (`/transcribe/start`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` | File | - | Audio file to transcribe (provide this OR `url`) |
| `url` | String | - | URL to audio file (provide this OR `file`) |
| `diarize` | Boolean | `true` | Enable speaker diarization |
| `language` | String | auto-detect | Language code (e.g., `en`, `es`, `fr`, `de`) |
| `translate` | Boolean | `false` | Translate output to English |
| `model_path` | String | `WHISPERX_MODEL` | Ignored; model set via `WHISPERX_MODEL` env var |
| `callback_url` | String | - | Webhook URL to POST results when complete |

#### Sync API (`/transcribe`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` | File | - | Audio file to transcribe (provide this OR `url`) |
| `url` | String | - | URL to audio file (provide this OR `file`) |
| `diarize` | Boolean | `true` | Enable speaker diarization |
| `language` | String | auto-detect | Language code (e.g., `en`, `es`, `fr`, `de`) |
| `translate` | Boolean | `false` | Translate output to English |
| `model_path` | String | `WHISPERX_MODEL` | Ignored; model set via `WHISPERX_MODEL` env var |

### Response Format

```json
{
  "ok": true,
  "text": "Full transcription text here...",
  "segments": [
    {
      "start": 0.0,
      "end": 2.5,
      "text": "First segment of speech"
    },
    {
      "start": 2.5,
      "end": 5.0,
      "text": "Second segment of speech"
    }
  ],
  "language": "en",
  "warnings": []
}
```

**Response Fields:**

- `ok` (boolean): `true` if transcription succeeded, `false` otherwise
- `text` (string): Full transcription text
- `segments` (array): Timestamped segments with start/end times in seconds
- `language` (string): Detected/source language code
- `warnings` (array|null): Alignment/diarization warnings (e.g., missing HF token)

### Queue Statistics

Monitor the job queue:

```bash
curl http://localhost:8080/queue/stats
```

Response:
```json
{
  "queued": 5,
  "running": 2,
  "done": 150,
  "error": 3
}
```

### Supported Audio Formats

The API supports any format that FFmpeg can decode, including:
- MP3
- WAV
- M4A
- FLAC
- OGG
- WEBM
- MP4 (audio track)

## Deploy to Google Cloud Run

### Prerequisites

- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) installed
- A Google Cloud project with billing enabled
- Cloud Run API enabled

### Deployment Steps

```bash
# Set your project ID
export PROJECT_ID=your-project-id
gcloud config set project $PROJECT_ID

# Build and push to Google Container Registry
docker build --platform linux/amd64 -t gcr.io/$PROJECT_ID/whisperx-cloudrun .
docker push gcr.io/$PROJECT_ID/whisperx-cloudrun

# Deploy to Cloud Run
gcloud run deploy whisperx-api-gpu \
  --image gcr.io/$PROJECT_ID/whisperx-cloudrun \
  --platform managed \
  --region us-central1 \
  --memory 16Gi \
  --cpu 4 \
  --timeout 600 \
  --gpu 1 --gpu-type nvidia-l4 --no-cpu-throttling --no-cpu-boost \
  --max-instances 1 \
  --allow-unauthenticated
```

### Environment Variables

You can set these during deployment:

```bash
gcloud run deploy whisperx-api-gpu \
  --image gcr.io/$PROJECT_ID/whisperx-cloudrun \
  --set-env-vars WHISPERX_MODEL=large-v3 \
  --set-env-vars RESULT_TTL_SECONDS=86400 \
  --set-env-vars WORKER_POLL_SEC=1.0 \
  --memory 16Gi \
  --cpu 4
```

#### Available Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPERX_MODEL` | `large-v3` | WhisperX model name |
| `WHISPERX_DEVICE` | `cuda` | Device to run on (GPU required) |
| `WHISPERX_COMPUTE_TYPE` | `float16` | Compute type for whisperX |
| `WHISPERX_BATCH_SIZE` | `16` | Batch size passed to `model.transcribe` |
| `WHISPERX_CACHE` | `/app/.cache/whisperx` | Cache dir for whisperX/align models |
| `HF_TOKEN` / `HUGGINGFACE_HUB_TOKEN` | - | Required for diarization model downloads |
| `PORT` | `8080` | Server port |
| `QUEUE_DB` | `/tmp/whisper_jobs.sqlite3` | SQLite database path |
| `RESULT_TTL_SECONDS` | `86400` | How long to keep completed jobs (1 day) |
| `WORKER_POLL_SEC` | `1.0` | Worker polling interval |
| `CLEANUP_INTERVAL_SEC` | `3600` | Job cleanup interval (1 hour) |

### Production Recommendations

- **GPU**: Cloud Run GPU (e.g., L4) or equivalent NVIDIA hardware
- **Memory**: 16Gi minimum for large-v3; scale up for heavy concurrency
- **CPU**: 4 vCPU recommended to keep the pipeline fed
- **Timeout**: 300s+ for long audio files; async API preferred
- **Max instances**: Tune based on throughput and GPU quota

## Development

### Project Structure

```
.
├── Dockerfile           # GPU whisperX build
├── server.py           # FastAPI application
├── entrypoint.sh       # Container entrypoint (starts uvicorn)
└── README.md           # This file
```

### Local Development

On Ubuntu, prefer the scripted install (`install-local-ubuntu.sh`) to set up system and Python deps in `.venv`. For non-Ubuntu systems, mirror the versions from `Dockerfile`:

```bash
pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
pip install numpy==2.0.2 fastapi uvicorn[standard] python-multipart requests transformers==4.48.1 nltk huggingface_hub
pip install whisperx==3.4.2 --no-deps
pip install faster-whisper==1.1.1 pandas pyannote.audio==3.3.2 "matplotlib<4"

# GPU default; set for CPU fallback:
# export WHISPERX_DEVICE=cpu WHISPERX_COMPUTE_TYPE=float32 WHISPERX_BATCH_SIZE=2
uvicorn server:app --reload --port 8080
```

## Troubleshooting

### Hugging Face auth errors

- Set `HF_TOKEN`/`HUGGINGFACE_HUB_TOKEN` when using diarization (pyannote) or private models.
- Ensure the token has access to `pyannote/speaker-diarization-3.1` if diarization is enabled.

### Out of memory errors

- Use a smaller model (e.g., `medium.en`) via `WHISPERX_MODEL`.
- Lower `WHISPERX_BATCH_SIZE` (default 16).
- Increase container memory/GPU RAM allocation.

### Slow transcription

- Use a smaller model.
- Verify the container has access to the GPU (`--gpus all` locally; Cloud Run GPU in production).
- Reduce diarization usage if not needed.

## License

This project relies on whisperX (MIT licensed). See the [whisperX repository](https://github.com/m-bain/whisperX) for details.
