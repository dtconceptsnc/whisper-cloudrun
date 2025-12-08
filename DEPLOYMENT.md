# Deployment Guide

Quick guide for deploying the GPU-only whisperX API to Google Cloud Run.

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
- Build the GPU Docker image for linux/amd64
- Push it to Google Container Registry
- Deploy to Cloud Run with default GPU settings (NVIDIA L4)

### Deploy with Custom Model

```bash
# Deploy with medium.en (faster, English-only)
./deploy.sh --model medium.en

# Deploy with large-v2 (multilingual)
./deploy.sh --model large-v2
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
MEMORY=16Gi \
CPU=4 \
TIMEOUT=600 \
MAX_INSTANCES=1 \
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

# Run the container (GPU required)
docker run --rm --gpus all -p 8080:8080 whisperx-cloudrun

# Test the API
curl http://localhost:8080/healthz
```

Want to run without Docker on Ubuntu? Use the local installer:

```bash
chmod +x install-local-ubuntu.sh
HF_TOKEN=your_hf_token ./install-local-ubuntu.sh
source .venv/bin/activate
PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu124 pip install -r requirements.txt  # only if you skip the script
uvicorn server:app --host 0.0.0.0 --port 8080
```

## Configuration Options

### Resource Allocation

| Resource | Default | Recommendation |
|----------|---------|----------------|
| GPU | 1x NVIDIA L4 | Required |
| Memory | 16Gi | 16Gi+ for large-v3 |
| CPU | 4 | 4 vCPU to feed the GPU |
| Timeout | 300s | 300-600s depending on file size |

### Available Models (whisperX)

| Model | Notes | Use Case |
|-------|-------|----------|
| large-v3 | Highest accuracy, multilingual | Best quality |
| large-v2 | Multilingual, slightly lighter | Quality with smaller VRAM |
| medium.en | English-only, faster | Meetings/podcasts in English |
| small.en | English-only, lightweight | Lower VRAM environments |

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
gcloud run services logs tail whisperx-api-gpu --region us-central1

# View recent logs
gcloud run services logs read whisperx-api-gpu --region us-central1 --limit 50
```

Check service details:

```bash
gcloud run services describe whisperx-api-gpu --region us-central1
```

## Updating the Service

```bash
# Deploy new version
./deploy.sh

# Rollback to previous version
gcloud run services update-traffic whisperx-api-gpu \
    --to-revisions=PREVIOUS_REVISION=100 \
    --region us-central1
```

## Cleanup

Delete the Cloud Run service:

```bash
gcloud run services delete whisperx-api-gpu --region us-central1
```

Delete container images:

```bash
# Container Registry
gcloud container images delete gcr.io/PROJECT_ID/whisperx-cloudrun

# Artifact Registry
gcloud artifacts docker images delete \
    us-central1-docker.pkg.dev/PROJECT_ID/cloudrun-images/whisperx-cloudrun
```
