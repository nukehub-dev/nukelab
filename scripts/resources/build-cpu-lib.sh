#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build the NukeLab CPU mask library image.
#
# The resulting image is consumed by environments/base/Dockerfile via
# COPY --from=nukelab-cpu-lib:latest. It is built locally and does not need
# to be published.
#
# Usage:
#   ./scripts/resources/build-cpu-lib.sh
#   ./scripts/resources/build-cpu-lib.sh --no-cache

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"
# shellcheck source=scripts/lib.sh
source "$DIR/../../scripts/lib.sh"

if [ -z "${CONTAINER_ENGINE:-}" ]; then
    detect_engine
fi

PROJECT_DIR="$DIR/../.."
IMAGE_NAME="${CPU_LIB_IMAGE:-nukelab-cpu-lib}"
TAG="latest"
NO_CACHE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --help | -h)
            cat << EOF
Usage: $0 [OPTIONS]

Options:
  --no-cache    Build without reusing the container layer cache
  --help, -h    Show this help message

Environment variables:
  CPU_LIB_IMAGE       Image name (default: nukelab-cpu-lib)
  CONTAINER_ENGINE    Container engine to use (podman|docker)
EOF
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

FULL_IMAGE="${IMAGE_NAME}:${TAG}"

log "Building NukeLab CPU mask library image..."
log "  Image: ${FULL_IMAGE}"
log "  Context: ${PROJECT_DIR}/resources/lib/nukelab"
log "  Builder: ${CONTAINER_ENGINE}"

cd "${PROJECT_DIR}/resources/lib/nukelab"

BUILD_OPTS=()
if [[ "$NO_CACHE" == true ]]; then
    BUILD_OPTS+=(--no-cache)
fi

$CONTAINER_ENGINE build \
    "${BUILD_OPTS[@]}" \
    --tag "${FULL_IMAGE}" \
    --file Dockerfile \
    .

log_ok "CPU mask library built successfully: ${FULL_IMAGE}"
