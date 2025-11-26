#!/usr/bin/env bash
set -euo pipefail

# WhisperX Cloud Run Deployment Script (GPU-only)
# Builds and deploys the whisperX API to Google Cloud Run with NVIDIA L4 GPU

# Configuration (GPU-only)
REGION="${REGION:-us-central1}"
MEMORY="${MEMORY:-16Gi}"
CPU="${CPU:-4}"
TIMEOUT="${TIMEOUT:-3600}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
PLATFORM="${PLATFORM:-managed}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI is not installed. Please install it from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Get project ID
PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")

if [ -z "$PROJECT_ID" ]; then
    log_error "No GCP project configured. Please run: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

log_info "Using project: $PROJECT_ID"

# Determine registry type (GCR or Artifact Registry)
USE_ARTIFACT_REGISTRY="${USE_ARTIFACT_REGISTRY:-false}"
if [ "$USE_ARTIFACT_REGISTRY" = "true" ]; then
    REGISTRY_LOCATION="${ARTIFACT_REGISTRY_LOCATION:-us-central1}"
    REPO_NAME="${ARTIFACT_REGISTRY_REPO:-cloudrun-images}"
    IMAGE_NAME="$REGISTRY_LOCATION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/whisperx-cloudrun"
    log_info "Using Artifact Registry: $IMAGE_NAME"
else
    IMAGE_NAME="gcr.io/$PROJECT_ID/whisperx-cloudrun"
    log_info "Using Container Registry: $IMAGE_NAME"
fi
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"

# Parse command line arguments
SKIP_BUILD=false
SKIP_PUSH=false
SKIP_DEPLOY=false
ALLOW_UNAUTHENTICATED=true
CUSTOM_MODEL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --service)
            SERVICE_NAME="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-push)
            SKIP_PUSH=true
            shift
            ;;
        --skip-deploy)
            SKIP_DEPLOY=true
            shift
            ;;
        --require-auth)
            ALLOW_UNAUTHENTICATED=false
            shift
            ;;
        --model|--model-url)
            CUSTOM_MODEL="$2"
            shift 2
            ;;
        --tag)
            IMAGE_TAG="$2"
            IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --service NAME       Cloud Run service name (default: whisperx-api-gpu)"
            echo "  --skip-build         Skip Docker image build"
            echo "  --skip-push          Skip pushing image to registry"
            echo "  --skip-deploy        Skip Cloud Run deployment"
            echo "  --require-auth       Require authentication for Cloud Run service"
            echo "  --model NAME         Set custom WhisperX model name (e.g., large-v2, medium.en)"
            echo "  --tag TAG            Image tag to build/push/deploy (default: latest)"
            echo "  --help               Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  SERVICE_NAME              Cloud Run service name (default: whisperx-api-gpu)"
            echo "  REGION                    Cloud Run region (default: us-central1)"
            echo "  MEMORY                    Memory allocation (default: 16Gi)"
            echo "  CPU                       CPU allocation (default: 4)"
            echo "  TIMEOUT                   Request timeout in seconds (default: 3600)"
            echo "  MAX_INSTANCES             Max instances (default: 1)"
            echo "  MIN_INSTANCES             Min instances (default: 0)"
            echo "  USE_ARTIFACT_REGISTRY     Use Artifact Registry instead of GCR (default: false)"
            echo "  ARTIFACT_REGISTRY_LOCATION Location for Artifact Registry (default: us-central1)"
            echo "  ARTIFACT_REGISTRY_REPO    Artifact Registry repository name (default: cloudrun-images)"
            echo "  IMAGE_TAG                 Image tag (default: latest)"
            echo "  HF_TOKEN                  REQUIRED at build time to pre-download diarization model"
            echo ""
            echo "Examples:"
            echo "  # Full deployment (GPU)"
            echo "  ./deploy.sh"
            echo ""
            echo "  # Deploy with custom model"
            echo "  ./deploy.sh --model medium.en"
            echo ""
            echo "  # Deploy to a new service name to avoid overwriting"
            echo "  ./deploy.sh --service whisperx-api-v2"
            echo ""
            echo "  # Only build, don't deploy"
            echo "  ./deploy.sh --skip-deploy"
            echo ""
            echo "  # Deploy with authentication required"
            echo "  ./deploy.sh --require-auth"
            echo ""
            echo "  # Use Artifact Registry"
            echo "  USE_ARTIFACT_REGISTRY=true ./deploy.sh"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Run '$0 --help' for usage information"
            exit 1
            ;;
    esac
done

SERVICE_NAME="${SERVICE_NAME:-whisperx-api-gpu}"
log_info "Using GPU service name: $SERVICE_NAME"
log_info "Image reference: $IMAGE_REF"

# Build Docker image
if [ "$SKIP_BUILD" = false ]; then
    if [ -z "${HF_TOKEN:-}" ]; then
        log_error "HF_TOKEN must be set for build (required to pre-download diarization model)."
        exit 1
    fi
    log_info "Building GPU-enabled Docker image for linux/amd64 with CUDA support..."
    if docker build --platform linux/amd64 --build-arg HF_TOKEN="$HF_TOKEN" -t "$IMAGE_REF" .; then
        log_success "GPU Docker image built successfully"
    else
        log_error "Failed to build GPU Docker image"
        exit 1
    fi
else
    log_warning "Skipping build step"
fi

# Push to registry
if [ "$SKIP_PUSH" = false ]; then
    log_info "Pushing image to registry..."

    # Configure docker auth for GCR/Artifact Registry
    if [ "$USE_ARTIFACT_REGISTRY" = "true" ]; then
        log_info "Configuring Artifact Registry authentication..."
        gcloud auth configure-docker "$REGISTRY_LOCATION-docker.pkg.dev" --quiet
    else
        log_info "Configuring Container Registry authentication..."
        gcloud auth configure-docker --quiet
    fi

    if docker push "$IMAGE_REF"; then
        log_success "Image pushed successfully"
    else
        log_error "Failed to push image"
        exit 1
    fi
else
    log_warning "Skipping push step"
fi

# Deploy to Cloud Run
if [ "$SKIP_DEPLOY" = false ]; then
    log_info "Deploying to Cloud Run..."

    # Build deployment command
    DEPLOY_CMD=(
        gcloud run deploy "$SERVICE_NAME"
        --image "$IMAGE_REF"
        --platform "$PLATFORM"
        --region "$REGION"
        --memory "$MEMORY"
        --cpu "$CPU"
        --timeout "$TIMEOUT"
        --max-instances "$MAX_INSTANCES"
        --min-instances "$MIN_INSTANCES"
    )

    # Add authentication setting
    if [ "$ALLOW_UNAUTHENTICATED" = true ]; then
        DEPLOY_CMD+=(--allow-unauthenticated)
    else
        DEPLOY_CMD+=(--no-allow-unauthenticated)
    fi

    # Add custom model if provided
    if [ -n "$CUSTOM_MODEL" ]; then
        DEPLOY_CMD+=(--set-env-vars "WHISPERX_MODEL=$CUSTOM_MODEL")
        log_info "Setting custom whisperX model: $CUSTOM_MODEL"
    fi

    # GPU settings (mandatory)
    DEPLOY_CMD+=(--gpu 1 --gpu-type nvidia-l4 --no-cpu-throttling --no-cpu-boost)
    log_info "Deploying with NVIDIA L4 GPU support"

    # Execute deployment
    if "${DEPLOY_CMD[@]}"; then
        log_success "Deployment successful!"
        echo ""

        # Get service URL
        SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
            --platform "$PLATFORM" \
            --region "$REGION" \
            --format 'value(status.url)' 2>/dev/null || echo "")

        if [ -n "$SERVICE_URL" ]; then
            log_success "Service URL: $SERVICE_URL"
            echo ""
            log_info "Test your deployment:"
            echo "  # Health check"
            echo "  curl $SERVICE_URL/healthz"
            echo ""
            echo "  # Transcribe audio file"
            echo "  curl -X POST $SERVICE_URL/transcribe -F 'file=@audio.mp3'"
            echo ""
            echo "  # Transcribe from URL"
            echo "  curl -X POST $SERVICE_URL/transcribe -F 'url=https://example.com/audio.mp3'"
        fi
    else
        log_error "Deployment failed"
        exit 1
    fi
else
    log_warning "Skipping deployment step"
fi

log_success "All steps completed!"
