#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause


# Build NukeLab default environment
set -e

echo "Building NukeLab default environment..."
cd "$(dirname "$0")/../environments/default"
podman build -t nukelab-default:latest .

echo "Default environment built successfully!"
