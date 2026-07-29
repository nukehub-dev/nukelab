#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build NukeLab dev/test terminal environment
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"
# shellcheck source=scripts/lib.sh
source "$DIR/../../scripts/lib.sh"

build_environment_image "$DIR" "dev environment" "dev" "nukelab-dev:latest" "$@"
