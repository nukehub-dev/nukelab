#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Generate /opt/nuke/nukelab-toolchain.json for a NukeLab toolchain image.

The manifest is produced by sourcing the toolchain activation script in a
clean environment (``env -i``) and capturing the variables it actually sets,
so values are fully resolved (no shell parameter expansion) and no build-host
variables leak in. PATH-family variables are recorded under ``env_prepend``
(the runtime prepends them to the container's existing values); all other
script-set variables go under ``env``.

This script is installed into the conda-base image as
``/usr/local/bin/nukelab-generate-toolchain-manifest``. Toolchain images in
the nukelab-environments repo inherit from conda-base and invoke it during
their own builds, right after copying their activation script:

    ARG TOOLCHAIN_VERSION=dev
    RUN nukelab-generate-toolchain-manifest \
        --name radiation-transport \
        --version "${TOOLCHAIN_VERSION}"
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys

# Variables whose values are colon-separated search paths. The spawner
# prepends these to the runtime container's existing values instead of
# replacing them.
PATH_VARS = [
    "PATH",
    "LD_LIBRARY_PATH",
    "LIBRARY_PATH",
    "CPATH",
    "C_INCLUDE_PATH",
    "CPLUS_INCLUDE_PATH",
    "PKG_CONFIG_PATH",
    "PYTHONPATH",
    "MANPATH",
]

# Shell bookkeeping variables that must never reach the manifest. The
# baseline diff below already excludes most of them; this filter catches any
# that change between the two runs (e.g. ``_``).
NOISE_VARS = {"PWD", "OLDPWD", "SHLVL", "_", "HOME", "HOSTNAME", "NUKE_DIR"}
NOISE_PREFIXES = ("CONDA_", "BASH_FUNC_")

# PATH-family variables are unset before sourcing so that expansions like
# ${PATH:+:${PATH}} resolve to only the toolchain's own absolute paths.
_UNSET_PATH_VARS = "unset " + " ".join(PATH_VARS)


def _clean_env(extra: str, nuke_dir: str) -> dict[str, str]:
    """Dump the environment of a clean bash shell after running *extra*."""
    # `env` must be resolved before PATH is unset, or the shell cannot find it.
    command = f'ENV_BIN=$(command -v env); {_UNSET_PATH_VARS}; {extra}"$ENV_BIN" -0'
    result = subprocess.run(
        ["env", "-i", f"NUKE_DIR={nuke_dir}", "bash", "-c", command],
        check=True,
        capture_output=True,
    )
    env = {}
    for entry in result.stdout.decode().split("\0"):
        if "=" in entry:
            key, value = entry.split("=", 1)
            env[key] = value
    return env


def capture_script_env(script: str, nuke_dir: str) -> dict[str, str]:
    """Source *script* in a clean environment and return the variables it sets.

    A baseline clean-shell dump is diffed against the post-source dump so
    exactly the script's own changes are captured — shell auto-set variables
    (``PWD``, ``SHLVL``, locale fallbacks) cancel out.
    """
    baseline = _clean_env("", nuke_dir)
    sourced = _clean_env(f". {shlex.quote(script)} 2>/dev/null || true; ", nuke_dir)
    return {k: v for k, v in sourced.items() if k not in baseline or baseline[k] != v}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a NukeLab toolchain manifest by sourcing the "
        "toolchain activation script in a clean environment."
    )
    parser.add_argument("--name", required=True, help="Toolchain name recorded in the manifest.")
    parser.add_argument(
        "--version", required=True, help="Toolchain version recorded in the manifest."
    )
    parser.add_argument(
        "--script",
        default="/opt/nuke/etc/toolchain-env.sh",
        help="Toolchain activation script to source (default: %(default)s).",
    )
    parser.add_argument(
        "--output",
        default="/opt/nuke/nukelab-toolchain.json",
        help="Manifest output path (default: %(default)s).",
    )
    parser.add_argument(
        "--nuke-dir",
        default=os.environ.get("NUKE_DIR", "/opt/nuke"),
        help="Toolchain root directory, exported as NUKE_DIR while sourcing "
        "(default: NUKE_DIR env or /opt/nuke).",
    )
    args = parser.parse_args()

    if not os.path.exists(args.script):
        print(f"ERROR: toolchain activation script not found: {args.script}", file=sys.stderr)
        return 1

    environ = {
        key: value
        for key, value in capture_script_env(args.script, args.nuke_dir).items()
        if key not in NOISE_VARS and not key.startswith(NOISE_PREFIXES)
    }
    manifest = {
        "name": args.name,
        "version": args.version,
        "mounts": [args.nuke_dir],
        "env": {k: environ[k] for k in sorted(environ) if k not in PATH_VARS},
        "env_prepend": {k: environ[k] for k in PATH_VARS if k in environ},
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"Wrote toolchain manifest for {args.name} {args.version}: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
