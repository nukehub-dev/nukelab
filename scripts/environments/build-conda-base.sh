#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build NukeLab conda-base environment
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"
# shellcheck source=scripts/lib.sh
source "$DIR/../../scripts/lib.sh"

build_environment_image "$DIR" "conda-base environment" "conda-base" "nukelab-conda-base:latest" --build-arg BASE_IMAGE=nukelab-base:latest "$@"
