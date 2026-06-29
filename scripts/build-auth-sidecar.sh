#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause


# Build the NukeLab auth sidecar Docker image
# This is a production-ready authentication sidecar for server containers.
#
# Usage:
#   ./scripts/build-auth-sidecar.sh
#   ./scripts/build-auth-sidecar.sh --push    # Build and push to registry
#   ./scripts/build-auth-sidecar.sh --tag v1.0.0

set -e

SCRIPT_DIR="$(dirname "$0")"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REGISTRY="${DOCKER_REGISTRY:-}"
IMAGE_NAME="${AUTH_SIDECAR_IMAGE:-nukelab-auth-sidecar}"
TAG="${1:-latest}"
PUSH=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH=true
            shift
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --registry)
            REGISTRY="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --push              Push image to registry after build"
            echo "  --tag TAG           Set image tag (default: latest)"
            echo "  --registry URL      Set Docker registry URL"
            echo "  --help, -h          Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  DOCKER_REGISTRY     Docker registry URL"
            echo "  AUTH_SIDECAR_IMAGE  Image name (default: nukelab-auth-sidecar)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Full image name
if [[ -n "$REGISTRY" ]]; then
    FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"
else
    FULL_IMAGE="${IMAGE_NAME}:${TAG}"
fi

echo "Building NukeLab auth sidecar..."
echo "  Image: ${FULL_IMAGE}"
echo "  Context: ${PROJECT_DIR}/services/auth-sidecar"

# Build the Docker image
cd "${PROJECT_DIR}/services/auth-sidecar"

if ! command -v docker &> /dev/null && ! command -v podman &> /dev/null; then
    echo "Error: Neither Docker nor Podman is installed"
    exit 1
fi

BUILDER="docker"
if ! command -v docker &> /dev/null; then
    BUILDER="podman"
fi

echo "Using builder: ${BUILDER}"

${BUILDER} build \
    --tag "${FULL_IMAGE}" \
    --file Dockerfile \
    .

echo "Auth sidecar built successfully: ${FULL_IMAGE}"

# Push if requested
if [[ "$PUSH" == true ]]; then
    echo "Pushing image to registry..."
    ${BUILDER} push "${FULL_IMAGE}"
    echo "Image pushed successfully"
fi

# Generate checksum for verification
echo ""
echo "Image details:"
${BUILDER} images "${FULL_IMAGE}" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
