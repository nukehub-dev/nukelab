#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Pre-populate a shared toolchain volume for fast server spawns.

This script is used by `./nukelabctl cache-toolchain <image>` to copy a
toolchain image into the shared named volume that the backend mounts at
server spawn time. Running it before any user spawn guarantees that the
first spawn on a node is fast.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid

# Import the canonical volume naming helper from the backend package.
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend")
sys.path.insert(0, _BACKEND_DIR)

from app.services.volume_service import make_toolchain_volume_name  # noqa: E402


def _detect_engine() -> str:
    """Return the container engine binary to use."""
    if os.environ.get("CONTAINER_ENGINE"):
        return os.environ["CONTAINER_ENGINE"]
    for binary in ("podman", "docker"):
        if subprocess.run(["which", binary], capture_output=True).returncode == 0:
            return binary
    raise RuntimeError("No container engine found (tried podman, docker).")


def _run(engine: str, *args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = [engine, *args]
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def _volume_exists(engine: str, name: str) -> bool:
    result = _run(engine, "volume", "inspect", name, check=False, capture=True)
    return result.returncode == 0


def _read_manifest(engine: str, image: str, volume_name: str) -> dict | None:
    """Read the toolchain manifest from the volume if it is populated."""
    container_name = f"nukelab-toolchain-manifest-{uuid.uuid4().hex[:8]}"
    try:
        result = _run(
            engine,
            "run",
            "--rm",
            "--name",
            container_name,
            "-v",
            f"{volume_name}:/opt/nuke:ro",
            image,
            "cat",
            "/opt/nuke/nukelab-toolchain.json",
            check=False,
            capture=True,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (json.JSONDecodeError, OSError):
        return None


def _populate(engine: str, image: str, volume_name: str, mount_paths: list[str]) -> None:
    """Copy toolchain image contents into the shared volume."""
    copy_script = ""
    for path in mount_paths:
        copy_script += f"mkdir -p /toolchain-target{path} && cp -a {path}/. /toolchain-target{path}/; "

    _run(
        engine,
        "run",
        "--rm",
        "-v",
        f"{volume_name}:/toolchain-target",
        image,
        "sh",
        "-c",
        copy_script,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-populate a NukeLab toolchain volume for fast server spawns."
    )
    parser.add_argument("image", help="Toolchain image reference (e.g. nukelab/radiation-transport:v1.2.3)")
    parser.add_argument(
        "--mount",
        action="append",
        default=["/opt/nuke"],
        help="Path(s) inside the image to copy into the shared volume (default: /opt/nuke).",
    )
    parser.add_argument(
        "--engine",
        default=os.environ.get("CONTAINER_ENGINE"),
        help="Container engine binary (default: auto-detect or CONTAINER_ENGINE env).",
    )
    args = parser.parse_args()

    engine = args.engine or _detect_engine()
    volume_name = make_toolchain_volume_name(args.image)

    print(f"Using container engine: {engine}")
    print(f"Toolchain image: {args.image}")
    print(f"Shared volume: {volume_name}")

    if not _volume_exists(engine, volume_name):
        print("Creating shared volume...")
        _run(engine, "volume", "create", volume_name)

    manifest = _read_manifest(engine, args.image, volume_name)
    if manifest is not None:
        print("Volume is already populated; nothing to do.")
        return 0

    print("Populating shared volume from image (this may take a while)...")
    _populate(engine, args.image, volume_name, args.mount)

    manifest = _read_manifest(engine, args.image, volume_name)
    if manifest is None:
        print("ERROR: Toolchain manifest missing after population.", file=sys.stderr)
        return 1

    print("Shared volume populated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
