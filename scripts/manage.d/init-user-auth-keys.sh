#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_init_user_auth_keys() {
    local secrets_dir="${USER_AUTH_SECRETS_DIR:-/run/user-secrets}"
    local private_name="user-auth-private.pem"
    local public_name="user-auth-public.pem"
    local vol_name="nukelab-user-secrets"

    step "Initializing user-auth Ed25519 key pair..."

    if ! command -v "$CONTAINER_ENGINE" > /dev/null 2>&1; then
        die "Container engine '$CONTAINER_ENGINE' not found"
    fi

    # Ensure the named volume exists so the temporary container can mount it.
    if ! "$CONTAINER_ENGINE" volume inspect "$vol_name" > /dev/null 2>&1; then
        info "Creating Docker/Podman volume: $vol_name"
        "$CONTAINER_ENGINE" volume create "$vol_name" > /dev/null || die "Failed to create volume $vol_name"
    fi

    # Check whether keys already exist.
    local existing
    existing=$("$CONTAINER_ENGINE" run --rm \
        -v "$vol_name:$secrets_dir" \
        --entrypoint sh \
        docker.io/library/python:3.13-slim \
        -c "test -f $secrets_dir/$private_name && test -f $secrets_dir/$public_name && echo yes || echo no" 2> /dev/null)

    if [ "$existing" = "yes" ]; then
        info "User-auth keys already exist in $vol_name; skipping generation."
        info "Use './nukelabctl rotate-user-auth-key' to replace them."
        return 0
    fi

    step "Generating Ed25519 key pair in $vol_name..."
    "$CONTAINER_ENGINE" run --rm \
        -v "$vol_name:$secrets_dir" \
        --entrypoint bash \
        docker.io/library/python:3.13-slim \
        -c "
pip install --quiet cryptography
python3 - <<'PY'
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import os

private_path = '$secrets_dir/$private_name'
public_path = '$secrets_dir/$public_name'
os.makedirs('$secrets_dir', mode=0o700, exist_ok=True)

key = Ed25519PrivateKey.generate()
private_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
public_pem = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

with open(private_path, 'wb') as f:
    f.write(private_pem)
os.chmod(private_path, 0o600)

with open(public_path, 'wb') as f:
    f.write(public_pem)
os.chmod(public_path, 0o644)

print(f'Generated {private_path} and {public_path}')
PY
"

    step "User-auth keys initialized."
}

help_init_user_auth_keys() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl init-user-auth-keys

Generate the initial Ed25519 key pair used to sign user API access tokens.
The keys are written to the 'nukelab-user-secrets' Docker/Podman volume,
which is mounted at /run/user-secrets inside the backend container.

This command is safe to run multiple times: if keys already exist, it does
nothing. In production, the backend refuses to start until these keys exist.

${BOLD}Examples:${RESET}
  ./nukelabctl init-user-auth-keys
EOF
}
