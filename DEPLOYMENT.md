# Deployment Guide

Quick guide for deploying the Whisper API to Google Cloud Run.

## Prerequisites

1. Install [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
2. Install [Docker](https://docs.docker.com/get-docker/)
3. Set up a GCP project with billing enabled
4. Authenticate with Google Cloud:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

## Quick Start

### Deploy Everything (Build + Push + Deploy)

```bash
./deploy.sh
```

This will:
- Build the Docker image for linux/amd64
- Push it to Google Container Registry
- Deploy to Cloud Run with default settings

### Deploy with Custom Model

```bash
# Deploy with small model (better accuracy than base)
./deploy.sh --model-url https://ggml.ggerganov.com/whisper/models/ggml-small.en.bin

# Deploy with tiny model (faster, less accurate)
./deploy.sh --model-url https://ggml.ggerganov.com/whisper/models/ggml-tiny.en.bin
```

### Deploy with Authentication Required

```bash
./deploy.sh --require-auth
```

## Advanced Usage

### Environment Variables

Customize deployment settings with environment variables:

```bash
# Deploy to different region with more resources
REGION=europe-west1 \
MEMORY=4Gi \
CPU=4 \
TIMEOUT=600 \
MAX_INSTANCES=20 \
./deploy.sh
```

### Use Artifact Registry (Recommended for new projects)

```bash
# First, create a repository in Artifact Registry
gcloud artifacts repositories create cloudrun-images \
    --repository-format=docker \
    --location=us-central1

# Then deploy
USE_ARTIFACT_REGISTRY=true ./deploy.sh
```

### Partial Deployments

```bash
# Only build the image locally
./deploy.sh --skip-push --skip-deploy

# Build and push, but don't deploy
./deploy.sh --skip-deploy

# Deploy previously built image
./deploy.sh --skip-build --skip-push
```

## Local Testing

Before deploying to Cloud Run, test locally:

```bash
# Quick build
./build-local.sh

# Run the container
docker run --rm -p 8080:8080 whisper-cloudrun

# Test the API
curl http://localhost:8080/healthz
```

## Configuration Options

### Resource Allocation

| Resource | Default | Recommendation |
|----------|---------|----------------|
| Memory | 2Gi | 2Gi for base, 4Gi+ for large models |
| CPU | 2 | 2-4 CPUs |
| Timeout | 300s | 300-600s depending on file size |

### Available Models

| Model | Size | Speed | Use Case |
|-------|------|-------|----------|
| ggml-tiny.en.bin | 75 MB | Fastest | Quick transcription, English only |
| ggml-base.en.bin | 142 MB | Fast | Default, good balance |
| ggml-small.en.bin | 466 MB | Medium | Better accuracy |
| ggml-medium.en.bin | 1.5 GB | Slow | High accuracy |
| ggml-large-v3.bin | 3.1 GB | Slowest | Best accuracy, multilingual |

## Cost Optimization

### For Low Traffic

```bash
# Use minimal resources, scale to zero
MIN_INSTANCES=0 \
MAX_INSTANCES=5 \
MEMORY=2Gi \
CPU=2 \
./deploy.sh
```

### For High Traffic

```bash
# Keep warm instance, allow more scaling
MIN_INSTANCES=1 \
MAX_INSTANCES=50 \
MEMORY=4Gi \
CPU=4 \
./deploy.sh
```

## Troubleshooting

### Build Fails

```bash
# Make sure you're building for the right platform
docker build --platform linux/amd64 -t test .
```

### Push Fails (Permission Denied)

```bash
# Reconfigure Docker authentication
gcloud auth configure-docker

# Or for Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev
```

### Deployment Timeout

Increase timeout and resources:

```bash
TIMEOUT=600 MEMORY=4Gi CPU=4 ./deploy.sh
```

### Cold Start Issues

Set minimum instances to keep service warm:

```bash
MIN_INSTANCES=1 ./deploy.sh
```

## Monitoring

View logs:

```bash
# Stream logs
gcloud run services logs tail whisper-api --region us-central1

# View recent logs
gcloud run services logs read whisper-api --region us-central1 --limit 50
```

Check service details:

```bash
gcloud run services describe whisper-api --region us-central1
```

## Updating the Service

```bash
# Deploy new version
./deploy.sh

# Rollback to previous version
gcloud run services update-traffic whisper-api \
    --to-revisions=PREVIOUS_REVISION=100 \
    --region us-central1
```

## Cleanup

Delete the Cloud Run service:

```bash
gcloud run services delete whisper-api --region us-central1
```

Delete container images:

```bash
# Container Registry
gcloud container images delete gcr.io/PROJECT_ID/whisper-cloudrun

# Artifact Registry
gcloud artifacts docker images delete \
    us-central1-docker.pkg.dev/PROJECT_ID/cloudrun-images/whisper-cloudrun
```
