#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build all NukeLab environments
set -e

SCRIPT_DIR="$(dirname "$0")"

echo "Building all NukeLab platform images..."
"$SCRIPT_DIR"/services/build-auth-sidecar.sh
"$SCRIPT_DIR"/environments/build-base.sh
"$SCRIPT_DIR"/environments/build-dev.sh
"$SCRIPT_DIR"/environments/build-workspace.sh

echo "All platform images built successfully!"
echo "Domain-specific environment images are built from the nukelab-environments repository."
