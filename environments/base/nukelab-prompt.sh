# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause
# shellcheck shell=bash

# Use the real human username for the shell identity and prompt, even though
# the hardened runtime runs every container as the fixed nukelab UID.
if [ -n "${NUKELAB_USERNAME:-}" ]; then
    export USER="$NUKELAB_USERNAME"
    export HOME="/home/$NUKELAB_USERNAME"
    export PS1="\[\e[0;32m\]${NUKELAB_USERNAME}@\[\e[0;36m\]NukeLab\[\e[0m\]:\w\$ "
fi
