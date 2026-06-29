#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause


# Build NukeLab dev environment
set -e

echo "Building NukeLab dev environment..."
cd "$(dirname "$0")/../environments/dev"
podman build -t nukelab-dev:latest .

echo "Dev environment built successfully!"
