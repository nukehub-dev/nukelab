#!/bin/bash

# Create user dynamically based on NUKELAB_USERNAME env var
USERNAME="${NUKELAB_USERNAME:-nukelab}"
USER_ID="${NUKELAB_USER_ID:-1000}"

# Create group and user with the provided username
if ! id "$USERNAME" &> /dev/null; then
    groupadd -r "$USERNAME" && \
    useradd -r -g "$USERNAME" -m -s /bin/bash -d "/home/$USERNAME" "$USERNAME"
    echo "Created user: $USERNAME (uid: $(id -u $USERNAME))"
fi

# Ensure home directory exists and is owned by the user
mkdir -p "/home/$USERNAME"
chown -R "$USERNAME:$USERNAME" "/home/$USERNAME"

# Start ttyd in background (running as the user)
ttyd --writable -p 7681 su - "$USERNAME" &

# Start nginx in foreground
nginx -g 'daemon off;'