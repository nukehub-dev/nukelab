#!/bin/bash

# Build NukeLab base image
set -e

echo "Building NukeLab base image..."
cd "$(dirname "$0")/../environments/base"
podman build -t nukelab-base:latest .

echo "Base image built successfully!"
