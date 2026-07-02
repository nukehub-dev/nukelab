#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

set -e

# The actual user this server is for. NUKELAB_USERNAME is the human username
# (e.g. admin). NUKELAB_CONTAINER_USER is the fixed system account the
# hardened runtime uses to run processes (nukelab, UID/GID 65532).
USERNAME="${NUKELAB_USERNAME:-nukelab}"
CONTAINER_USER="${NUKELAB_CONTAINER_USER:-nukelab}"

# Make system tools (whoami, id, ls -l) report the human username instead of
# the fixed hardened-runtime account. libnss-wrapper intercepts passwd/group
# lookups. This is needed because the container is locked to UID/GID 65532.
# The backend may also set these via container env so every process (including
# terminals spawned by Theia) sees the real username.
NSS_WRAPPER_SO=""
for path in /usr/lib/x86_64-linux-gnu/libnss_wrapper.so \
    /usr/lib/libnss_wrapper.so \
    /lib/x86_64-linux-gnu/libnss_wrapper.so; do
    if [ -f "$path" ]; then
        NSS_WRAPPER_SO="$path"
        break
    fi
done

if [ -n "$NSS_WRAPPER_SO" ]; then
    NSS_WRAPPER_PASSWD="${NSS_WRAPPER_PASSWD:-/tmp/nukelab-passwd}"
    NSS_WRAPPER_GROUP="${NSS_WRAPPER_GROUP:-/tmp/nukelab-group}"
    echo "${USERNAME}:x:65532:65532:${USERNAME}:/home/${USERNAME}:/bin/bash" > "$NSS_WRAPPER_PASSWD"
    echo "${USERNAME}:x:65532:" > "$NSS_WRAPPER_GROUP"
    export NSS_WRAPPER_PASSWD
    export NSS_WRAPPER_GROUP
    # Prepend nss-wrapper to any existing LD_PRELOAD (e.g. libnukelab_cpu.so).
    case ":${LD_PRELOAD}:" in
        *:"$NSS_WRAPPER_SO":*) ;;
        *) export LD_PRELOAD="${NSS_WRAPPER_SO}${LD_PRELOAD:+:${LD_PRELOAD}}" ;;
    esac
fi

RUN_AS_ROOT=false
if [ "$(id -u)" -eq 0 ]; then
    RUN_AS_ROOT=true
fi

# Create group and user with the provided username when running as root.
# The hardened runtime starts the container as the pre-created container user,
# so the useradd path is skipped in that case.
if $RUN_AS_ROOT && ! id "$USERNAME" &> /dev/null; then
    groupadd -r "$USERNAME" \
        && useradd -r -g "$USERNAME" -m -s /bin/bash -d "/home/$USERNAME" "$USERNAME"
    echo "Created user: $USERNAME (uid: $(id -u "$USERNAME"))"
fi

# Ensure home directory exists and is accessible.
# When running as root we make the mount point world-writable (non-recursive)
# to avoid slow recursive chown on large volumes and ownership fights when the
# same volume is shared across multiple users. When running as non-root we
# assume the backend/spawner has already arranged writable permissions.
mkdir -p "/home/$USERNAME"
if $RUN_AS_ROOT; then
    chmod 777 "/home/$USERNAME"
fi

# Export a friendly shell prompt and identity.
export HOME="/home/$USERNAME"
export USER="$USERNAME"
export PS1="\[\e[0;32m\]${USERNAME}@\[\e[0;36m\]NukeLab\[\e[0m\]:\w\$ "

# If the home directory is empty (e.g., fresh named volume), copy default
# dotfiles from /etc/skel so the user has a functional shell environment.
if [ -z "$(ls -A /home/"$USERNAME" 2> /dev/null)" ]; then
    cp -r /etc/skel/. /home/"$USERNAME"/ 2> /dev/null || true
    if $RUN_AS_ROOT; then
        # Ensure the copied files are owned by the container UID so the
        # hardened (non-root) runtime can read/write its own home later.
        chown -R nukelab:nukelab /home/"$USERNAME" 2> /dev/null || true
        chmod -R u+rw /home/"$USERNAME" 2> /dev/null || true
    fi
fi

# Make sure existing (or copied) .bashrc shows the human username in the prompt.
# The hardened runtime runs the container as the fixed nukelab UID, so bash
# would otherwise display "nukelab" even though the real user is $USERNAME.
BASHRC="/home/$USERNAME/.bashrc"
PROMPT_MARKER="# NukeLab: show the human username"
if [ -f "$BASHRC" ] && ! grep -q "$PROMPT_MARKER" "$BASHRC" 2> /dev/null; then
    PROMPT_SNIPPET='
# NukeLab: show the human username in the prompt
if [ -n "${NUKELAB_USERNAME:-}" ]; then
    export USER="$NUKELAB_USERNAME"
    export HOME="/home/$NUKELAB_USERNAME"
    export PS1="\[\e[0;32m\]${NUKELAB_USERNAME}@\[\e[0;36m\]NukeLab\[\e[0m\]:\w\$ "
fi
'
    if [ -w "$BASHRC" ]; then
        printf '%s' "$PROMPT_SNIPPET" >> "$BASHRC"
    else
        # The existing .bashrc is root-owned (e.g., from an earlier non-hardened
        # run). The home directory is world-writable, so we can replace it with
        # a version the container user owns.
        TMP_RC="/home/$USERNAME/.bashrc.new.$$"
        if cp "$BASHRC" "$TMP_RC" 2> /dev/null; then
            printf '%s' "$PROMPT_SNIPPET" >> "$TMP_RC"
            mv -f "$TMP_RC" "$BASHRC" 2> /dev/null || rm -f "$TMP_RC"
        fi
    fi
fi

# Start auth sidecar in background on an unprivileged port so nginx can bind
# 8080 while the sidecar binds 8081.
if [ "${NUKELAB_AUTH_ENABLED:-true}" = "true" ]; then
    echo "Starting auth sidecar..."
    NUKELAB_AUTH_LISTEN_ADDR="${NUKELAB_AUTH_LISTEN_ADDR:-:8081}" auth-sidecar &
    AUTH_PID=$!

    # Wait for auth sidecar to be ready
    for _ in {1..10}; do
        if curl -sf "http://localhost:${NUKELAB_AUTH_LISTEN_ADDR##*:}/health" > /dev/null 2>&1; then
            echo "Auth sidecar is ready"
            break
        fi
        sleep 1
    done
fi

# Start the user-provided application command in the background.
# Child environments set NUKELAB_START_COMMAND to launch their service
if [ -n "${NUKELAB_START_COMMAND:-}" ]; then
    echo "Starting application: $NUKELAB_START_COMMAND"
    eval "$NUKELAB_START_COMMAND" &
fi

# Start nginx in foreground
exec nginx -g 'daemon off;'
