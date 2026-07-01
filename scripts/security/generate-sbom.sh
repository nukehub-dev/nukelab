#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Generate CycloneDX SBOM artifacts for NukeLab.
#
# Uses Trivy when available (container engine required). Outputs are written to
# backend/reports/security/sbom/ so they can be attached to release artifacts.
#
# Usage:
#   ./scripts/security/generate-sbom.sh [options]
#
# Options:
#   --images-only     Only generate SBOMs for locally built container images
#   --fs-only         Only generate SBOMs for the repository filesystem
#   -h, --help        Show this help message

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SBOM_DIR="${REPO_ROOT}/backend/reports/security/sbom"

SBOM_IMAGES=true
SBOM_FS=true

# Prefer podman, then docker.
CONTAINER_ENGINE=""
TRIVY_IMAGE="ghcr.io/aquasecurity/trivy:latest"

show_help() {
    cat << EOF
${0}: Generate CycloneDX SBOMs for NukeLab.

Usage: ${0} [options]

Options:
  --images-only     Only generate SBOMs for locally built container images
  --fs-only         Only generate SBOMs for the repository filesystem
  -h, --help        Show this help message

Outputs:
  ${SBOM_DIR}/sbom-backend.json
  ${SBOM_DIR}/sbom-frontend.json
  ${SBOM_DIR}/sbom-<image>.json
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --images-only)
            SBOM_FS=false
            shift
            ;;
        --fs-only)
            SBOM_IMAGES=false
            shift
            ;;
        -h | --help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            show_help
            exit 1
            ;;
    esac
done

mkdir -p "${SBOM_DIR}"

_detect_engine() {
    if command -v podman > /dev/null 2>&1; then
        CONTAINER_ENGINE=podman
    elif command -v docker > /dev/null 2>&1; then
        CONTAINER_ENGINE=docker
    else
        echo "WARNING: No container engine found; skipping image SBOM generation." >&2
        return 1
    fi
}

_run_trivy_sbom() {
    local target="$1"
    local output="$2"
    local extra_args=()

    if [[ "$target" == *"/"* || "$target" == "." ]]; then
        extra_args=("fs")
    else
        extra_args=("image")
    fi

    "${CONTAINER_ENGINE}" run --rm \
        -v "${REPO_ROOT}:${REPO_ROOT}:ro" \
        -v "${SBOM_DIR}:${SBOM_DIR}:rw" \
        "${TRIVY_IMAGE}" "${extra_args[@]}" \
        --format cyclonedx \
        --output "${output}" \
        "${target}" 2> /dev/null || true
}

if $SBOM_FS; then
    if ! _detect_engine; then
        echo "Skipping filesystem SBOMs (no container engine)."
    else
        echo "Generating filesystem SBOMs..."
        _run_trivy_sbom "${REPO_ROOT}/backend" "${SBOM_DIR}/sbom-backend.json"
        _run_trivy_sbom "${REPO_ROOT}/frontend" "${SBOM_DIR}/sbom-frontend.json"
    fi
fi

if $SBOM_IMAGES; then
    if ! _detect_engine; then
        echo "Skipping image SBOMs (no container engine)."
    else
        echo "Generating image SBOMs..."
        images=(
            "nukelab-backend:latest"
            "nukelab-frontend:latest"
            "nukelab-auth-sidecar:latest"
            "nukelab-base:latest"
            "nukelab-workspace:latest"
            "nukelab-default:latest"
        )
        for image in "${images[@]}"; do
            image_exists=false
            if [ "$CONTAINER_ENGINE" = "podman" ]; then
                "${CONTAINER_ENGINE}" image exists "$image" 2> /dev/null && image_exists=true || true
            else
                [ -n "$(${CONTAINER_ENGINE} images -q "$image" 2> /dev/null)" ] && image_exists=true || true
            fi
            if ! $image_exists; then
                echo "Skipping ${image}: not found locally"
                continue
            fi
            safe_name="${image//\//-}"
            _run_trivy_sbom "$image" "${SBOM_DIR}/sbom-${safe_name}.json"
        done
    fi
fi

echo ""
echo "SBOM outputs in: ${SBOM_DIR}"
ls -1 "${SBOM_DIR}" 2> /dev/null || true
