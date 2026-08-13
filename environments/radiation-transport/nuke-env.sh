# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause
# shellcheck shell=bash

# In the radiation-transport environment, activate the dedicated nuclear
# conda environment in login/interactive shells so users get the right Python
# and the MOAB/OpenMC/PyNE toolchain.
if [ -n "${NUKE_DIR:-}" ] && [ -d "${NUKE_DIR}/bin" ]; then
    # Conda activation replaces PATH with the env's bin directory. The Dockerfile
    # adds nuclear-code bin directories to PATH; preserve them across activation
    # so openmc, geant4-config, njoy, etc. remain available in terminals.
    _nuke_tool_path="${NUKE_DIR}/bin"
    _nuke_tool_path="${_nuke_tool_path}:${MOAB_ROOT:-/opt/moab}/bin"
    _nuke_tool_path="${_nuke_tool_path}:${DOUBLE_DOWN_ROOT:-/opt/double-down}/lib"
    _nuke_tool_path="${_nuke_tool_path}:${GEANT4_ROOT:-/opt/geant4}/bin"
    _nuke_tool_path="${_nuke_tool_path}:${DAGMC_ROOT:-/opt/dagmc}/bin"
    _nuke_tool_path="${_nuke_tool_path}:${LIBMESH_ROOT:-/opt/libmesh}/bin"
    _nuke_tool_path="${_nuke_tool_path}:${NJOY2016_ROOT:-/opt/njoy2016}/bin"
    _nuke_tool_path="${_nuke_tool_path}:${OPENMC_ROOT:-/opt/openmc}/bin"
    _nuke_tool_path="${_nuke_tool_path}:${KDSOURCE_ROOT:-/opt/kdsource}/bin"
    _nuke_tool_path="${_nuke_tool_path}:${ALARA_ROOT:-/opt/alara}/bin"

    conda activate "${NUKE_DIR}" > /dev/null 2>&1 || true

    export PATH="${_nuke_tool_path}${PATH:+:${PATH}}"
    unset _nuke_tool_path

    # The nuke env replaces PATH with its own bin directory. Keep the base
    # conda tools (node, yarn, npm) available in login/terminal sessions.
    if [ -d "/opt/conda/bin" ] && [[ ":${PATH}:" != *":/opt/conda/bin:"* ]]; then
        export PATH="${PATH}:/opt/conda/bin"
    fi
fi
