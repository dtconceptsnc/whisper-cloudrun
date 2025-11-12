# Whisper Cloud Run API

A containerized Whisper API powered by [whisper.cpp](https://github.com/ggerganov/whisper.cpp), designed for deployment on Google Cloud Run or any Docker-compatible environment.

## Features

- Fast CPU-based transcription using whisper.cpp
- Automatic model downloading on first run
- Speaker diarization support
- Multi-language support
- Translation to English
- Accepts both file uploads and URLs

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
  --memory 2Gi \
  --cpu 2
```

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
