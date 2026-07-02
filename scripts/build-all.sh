#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause


# Build all NukeLab environments
set -e

SCRIPT_DIR="$(dirname "$0")"

echo "Building all NukeLab components..."
"$SCRIPT_DIR"/build-auth-sidecar.sh
"$SCRIPT_DIR"/build-base.sh
"$SCRIPT_DIR"/build-dev.sh
"$SCRIPT_DIR"/build-workspace.sh
"$SCRIPT_DIR"/build-radiation-transport.sh

echo "All components built successfully!"
