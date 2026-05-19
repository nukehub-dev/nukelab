#!/bin/bash

set -e

# Create user dynamically based on NUKELAB_USERNAME env var
USERNAME="${NUKELAB_USERNAME:-nukelab}"
USER_ID="${NUKELAB_USER_ID:-1000}"

# Create group and user with the provided username
if ! id "$USERNAME" &> /dev/null; then
    groupadd -r "$USERNAME" && \
    useradd -r -g "$USERNAME" -m -s /bin/bash -d "/home/$USERNAME" "$USERNAME"
    echo "Created user: $USERNAME (uid: $(id -u $USERNAME))"
fi

# Ensure home directory exists and is accessible.
# We use chmod 777 on the mount point (non-recursive) instead of chown -R
# to avoid two problems:
#   1. Slow startup on large volumes (50GB / 100k files)
#   2. Ownership fights when the same volume is shared across multiple users
mkdir -p "/home/$USERNAME"
chmod 777 "/home/$USERNAME"

# If the home directory is empty (e.g., fresh named volume), copy default
# dotfiles from /etc/skel so the user has a functional shell environment.
if [ -z "$(ls -A /home/$USERNAME 2>/dev/null)" ]; then
    cp -r /etc/skel/. /home/$USERNAME/ 2>/dev/null || true
    chmod -R u+rw /home/$USERNAME 2>/dev/null || true
fi

# Start auth sidecar in background
# This validates server access tokens locally using the public key
if [ "${NUKELAB_AUTH_ENABLED:-true}" = "true" ]; then
    echo "Starting auth sidecar..."
    auth-sidecar &
    AUTH_PID=$!
    
    # Wait for auth sidecar to be ready
    for i in {1..10}; do
        if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
            echo "Auth sidecar is ready"
            break
        fi
        sleep 1
    done
fi

# Start ttyd in background (running as the user)
ttyd --writable -p 7681 su - "$USERNAME" &

# Start nginx in foreground
nginx -g 'daemon off;'