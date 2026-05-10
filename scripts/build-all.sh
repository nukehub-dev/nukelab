#!/bin/bash

# Build all NukeLab environments
set -e

SCRIPT_DIR="$(dirname "$0")"

echo "Building all NukeLab components..."
$SCRIPT_DIR/build-auth-sidecar.sh
$SCRIPT_DIR/build-base.sh
$SCRIPT_DIR/build-dev.sh

echo "All components built successfully!"
