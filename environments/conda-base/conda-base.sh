# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause
# shellcheck shell=bash

# The conda profile script puts only condabin on PATH for login shells.
# Activate the base environment so node, yarn, and python from conda are
# available in interactive/terminal sessions.
if [ -n "${CONDA_EXE:-}" ] && [ -z "${CONDA_DEFAULT_ENV:-}" ]; then
    conda activate base > /dev/null 2>&1 || true
fi
