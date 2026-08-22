#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build NukeLab base image
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"
# shellcheck source=scripts/lib.sh
source "$DIR/../../scripts/lib.sh"

# The base image embeds the CPU mask library built by scripts/resources/build-cpu-lib.sh,
# so build that image first whenever the base image is requested.
log "Building CPU mask library image (required by the base image)"
_run_quiet_unless_verbose bash "$DIR/../resources/build-cpu-lib.sh" "$@"

build_environment_image "$DIR" "base image" "base" "nukelab-base:latest" "$@"
