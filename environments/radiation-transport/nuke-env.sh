# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause
# shellcheck shell=bash

# In the radiation-transport environment, activate the dedicated nuclear
# conda environment in login/interactive shells so users get the right Python
# and the MOAB/OpenMC/PyNE toolchain.
if [ -n "${NUKE_DIR:-}" ] && [ -d "${NUKE_DIR}/bin" ]; then
    conda activate "${NUKE_DIR}" > /dev/null 2>&1 || true
    # The nuke env replaces PATH with its own bin directory. Keep the base
    # conda tools (node, yarn, npm) available in login/terminal sessions.
    if [ -d "/opt/conda/bin" ] && [[ ":${PATH}:" != *":/opt/conda/bin:"* ]]; then
        export PATH="${PATH}:/opt/conda/bin"
    fi
fi
