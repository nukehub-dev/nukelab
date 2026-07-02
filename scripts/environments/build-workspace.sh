#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build NukeLab workspace environment
set -e

echo "Building NukeLab workspace environment..."
cd "$(dirname "$0")/../../environments/workspace"
podman build -t nukelab-workspace:latest .

echo "Workspace environment built successfully!"
