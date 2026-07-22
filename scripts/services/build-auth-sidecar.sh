#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build the NukeLab auth sidecar container image
# This is a production-ready authentication sidecar for server containers.
#
# Usage:
#   ./scripts/services/build-auth-sidecar.sh
#   ./scripts/services/build-auth-sidecar.sh --push    # Build and push to registry
#   ./scripts/services/build-auth-sidecar.sh --tag v1.0.0

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"
# shellcheck source=scripts/lib.sh
source "$DIR/../../scripts/lib.sh"

if [ -z "${CONTAINER_ENGINE:-}" ]; then
    detect_engine
fi

PROJECT_DIR="$DIR/../.."
REGISTRY="${DOCKER_REGISTRY:-}"
IMAGE_NAME="${AUTH_SIDECAR_IMAGE:-nukelab-auth-sidecar}"
TAG="latest"
PUSH=false
NO_CACHE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH=true
            shift
            ;;
        --no-cache)
            NO_CACHE=true
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
        --help | -h)
            cat << EOF
Usage: $0 [OPTIONS]

Options:
  --push              Push image to registry after build
  --no-cache          Build without reusing the container layer cache
  --tag TAG           Set image tag (default: latest)
  --registry URL      Set Docker registry URL
  --help, -h          Show this help message

Environment variables:
  DOCKER_REGISTRY     Docker registry URL
  AUTH_SIDECAR_IMAGE  Image name (default: nukelab-auth-sidecar)
  CONTAINER_ENGINE    Container engine to use (podman|docker)
EOF
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

if [[ -n "$REGISTRY" ]]; then
    FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"
else
    FULL_IMAGE="${IMAGE_NAME}:${TAG}"
fi

log "Building NukeLab auth sidecar..."
log "  Image: ${FULL_IMAGE}"
log "  Context: ${PROJECT_DIR}/services/auth-sidecar"
log "  Builder: ${CONTAINER_ENGINE}"

cd "${PROJECT_DIR}/services/auth-sidecar"

BUILD_OPTS=()
if [[ "$NO_CACHE" == true ]]; then
    BUILD_OPTS+=(--no-cache)
fi

$CONTAINER_ENGINE build \
    "${BUILD_OPTS[@]}" \
    --tag "${FULL_IMAGE}" \
    --file Dockerfile \
    .

log_ok "Auth sidecar built successfully: ${FULL_IMAGE}"

if [[ "$PUSH" == true ]]; then
    log "Pushing image to registry..."
    $CONTAINER_ENGINE push "${FULL_IMAGE}"
    log_ok "Image pushed successfully"
fi

log "Image details:"
$CONTAINER_ENGINE images "${FULL_IMAGE}" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
