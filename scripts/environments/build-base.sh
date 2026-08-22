#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build NukeLab base image
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"
# shellcheck source=scripts/lib.sh
source "$DIR/../../scripts/lib.sh"

# The base Dockerfile builds the CPU mask library inline from
# resources/lib/nukelab/libnukelab_cpu.c, so the build context must be the
# repository root instead of environments/base.
ROOT_DIR="$(cd "$DIR/../.." > /dev/null 2>&1 && pwd)"

if [ -z "${CONTAINER_ENGINE:-}" ]; then
    detect_engine
fi

log "Building NukeLab base image..."
cd "$ROOT_DIR"
$CONTAINER_ENGINE build \
    -t "nukelab-environment-base:latest" \
    -f "environments/base/Dockerfile" \
    "$@" \
    .

log_ok "base image built successfully!"
