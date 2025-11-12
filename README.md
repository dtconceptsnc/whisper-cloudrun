# Whisper Cloud Run API

A containerized Whisper API powered by [whisper.cpp](https://github.com/ggerganov/whisper.cpp), designed for deployment on Google Cloud Run or any Docker-compatible environment.

## Features

- Fast CPU-based transcription using whisper.cpp
- **Async job queue** - handles long-running transcriptions without timeout
- **Callback support** - integrates with n8n, webhooks, and automation tools
- Automatic model downloading on first run
- Speaker diarization support
- Multi-language support
- Translation to English
- Accepts both file uploads and URLs
- Queue statistics and monitoring

## Quick Start

### Build and Run Locally

```bash
# Build the Docker image (for amd64/Cloud Run)
docker build --platform linux/amd64 -t whisper-cloudrun .

# Run locally
docker run --rm -p 8080:8080 whisper-cloudrun
```

### Run with Custom Model

```bash
docker run --rm -p 8080:8080 \
  -e WHISPER_MODEL_URL=https://ggml.ggerganov.com/whisper/models/ggml-large-v3.bin \
  whisper-cloudrun
```

Available models:
- `ggml-tiny.en.bin` (75 MB) - English only, fastest
- `ggml-base.en.bin` (142 MB) - English only, good balance (default)
- `ggml-small.en.bin` (466 MB) - English only, better accuracy
- `ggml-medium.en.bin` (1.5 GB) - English only, high accuracy
- `ggml-large-v3.bin` (3.1 GB) - Multilingual, best accuracy

See [whisper.cpp models](https://github.com/ggerganov/whisper.cpp/tree/master/models) for the full list.

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
    "cmd": "Command executed",
    "stderr": "Processing info"
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
  "cmd": "...",
  "stderr": "..."
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
| `model_path` | String | `/app/models/ggml-base.en.bin` | Custom model path (advanced) |
| `callback_url` | String | - | Webhook URL to POST results when complete |

#### Sync API (`/transcribe`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` | File | - | Audio file to transcribe (provide this OR `url`) |
| `url` | String | - | URL to audio file (provide this OR `file`) |
| `diarize` | Boolean | `true` | Enable speaker diarization |
| `language` | String | auto-detect | Language code (e.g., `en`, `es`, `fr`, `de`) |
| `translate` | Boolean | `false` | Translate output to English |
| `model_path` | String | `/app/models/ggml-base.en.bin` | Custom model path (advanced) |

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
  "cmd": "Command that was executed",
  "stderr": "Any warnings or errors from whisper.cpp"
}
```

**Response Fields:**

- `ok` (boolean): `true` if transcription succeeded, `false` otherwise
- `text` (string): Full transcription text
- `segments` (array): Timestamped segments with start/end times in seconds
- `cmd` (string): The actual whisper.cpp command that was executed
- `stderr` (string): Standard error output from whisper.cpp (warnings, debug info)

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
docker build --platform linux/amd64 -t gcr.io/$PROJECT_ID/whisper-cloudrun .
docker push gcr.io/$PROJECT_ID/whisper-cloudrun

# Deploy to Cloud Run
gcloud run deploy whisper-api \
  --image gcr.io/$PROJECT_ID/whisper-cloudrun \
  --platform managed \
  --region us-central1 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 10 \
  --allow-unauthenticated
```

### Environment Variables

You can set these during deployment:

```bash
gcloud run deploy whisper-api \
  --image gcr.io/$PROJECT_ID/whisper-cloudrun \
  --set-env-vars WHISPER_MODEL_URL=https://ggml.ggerganov.com/whisper/models/ggml-small.en.bin \
  --set-env-vars RESULT_TTL_SECONDS=86400 \
  --set-env-vars WORKER_POLL_SEC=1.0 \
  --memory 2Gi \
  --cpu 2
```

#### Available Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_MODEL_URL` | `ggml-base.en.bin` | URL to download whisper model |
| `WHISPER_MODEL` | `/app/models/ggml-base.en.bin` | Path to model file |
| `WHISPER_DIR` | `/app/whisper.cpp` | Path to whisper.cpp directory |
| `WHISPER_EXE` | `/app/whisper.cpp/main` | Path to whisper executable |
| `PORT` | `8080` | Server port |
| `QUEUE_DB` | `/tmp/whisper_jobs.sqlite3` | SQLite database path |
| `RESULT_TTL_SECONDS` | `86400` | How long to keep completed jobs (1 day) |
| `WORKER_POLL_SEC` | `1.0` | Worker polling interval |
| `CLEANUP_INTERVAL_SEC` | `3600` | Job cleanup interval (1 hour) |

### Production Recommendations

- **Memory**: At least 2GB for base model, 4GB+ for large models
- **CPU**: At least 2 CPUs for reasonable performance
- **Timeout**: 300s (5 minutes) for longer audio files
- **Max instances**: Adjust based on your expected load

## Development

### Project Structure

```
.
├── Dockerfile           # Multi-stage build for whisper.cpp + API
├── server.py           # FastAPI application
├── entrypoint.sh       # Container entrypoint with model download
└── README.md           # This file
```

### Local Development

```bash
# Install dependencies
pip install fastapi uvicorn[standard] python-multipart

# Run locally (requires whisper.cpp built separately)
export WHISPER_DIR=/path/to/whisper.cpp
export WHISPER_MODEL=/path/to/model.bin
uvicorn server:app --reload --port 8080
```

## Troubleshooting

### Model download fails

If the model download hangs or fails, you can pre-download it and mount as a volume:

```bash
# Download model locally
wget https://ggml.ggerganov.com/whisper/models/ggml-base.en.bin -O ggml-base.en.bin

# Mount it into the container
docker run --rm -p 8080:8080 \
  -v $(pwd)/ggml-base.en.bin:/app/models/ggml-base.en.bin \
  whisper-cloudrun
```

### Out of memory errors

Use a smaller model or increase memory allocation:

```bash
docker run --rm -p 8080:8080 \
  -e WHISPER_MODEL_URL=https://ggml.ggerganov.com/whisper/models/ggml-tiny.en.bin \
  --memory 1g \
  whisper-cloudrun
```

### Slow transcription

- Use a smaller model (tiny or base instead of large)
- Increase CPU allocation
- Consider GPU deployment for high-throughput scenarios

## License

This project uses whisper.cpp which is MIT licensed. See the [whisper.cpp repository](https://github.com/ggerganov/whisper.cpp) for details.
