#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build all NukeLab environments
set -e

SCRIPT_DIR="$(dirname "$0")"

echo "Building all NukeLab components..."
"$SCRIPT_DIR"/services/build-auth-sidecar.sh
"$SCRIPT_DIR"/environments/build-base.sh
"$SCRIPT_DIR"/environments/build-dev.sh
"$SCRIPT_DIR"/environments/build-workspace.sh
"$SCRIPT_DIR"/environments/build-radiation-transport.sh
"$SCRIPT_DIR"/environments/build-gpu.sh

echo "All components built successfully!"
