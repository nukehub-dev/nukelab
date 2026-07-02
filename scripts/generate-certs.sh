#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Generate self-signed SSL certificates for development
set -e

CERTS_DIR="$(dirname "$0")/../certs"
mkdir -p "$CERTS_DIR"

echo "Generating self-signed SSL certificates..."

# Generate private key
openssl genrsa -out "$CERTS_DIR/key.pem" 2048

# Generate certificate
openssl req -new -x509 -key "$CERTS_DIR/key.pem" -out "$CERTS_DIR/cert.pem" -days 365 \
    -subj "/C=US/ST=State/L=City/O=NukeLab/OU=Development/CN=localhost"

# Set permissions
chmod 600 "$CERTS_DIR/key.pem"
chmod 644 "$CERTS_DIR/cert.pem"

echo "Certificates generated in $CERTS_DIR/"
echo "  - cert.pem"
echo "  - key.pem"
