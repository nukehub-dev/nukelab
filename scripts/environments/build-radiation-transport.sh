#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build NukeLab radiation-transport environment
set -e

echo "Building NukeLab radiation-transport environment..."
cd "$(dirname "$0")/../../environments/radiation-transport"
podman build -t nukelab-radiation-transport:latest .

echo "Radiation-transport environment built successfully!"
