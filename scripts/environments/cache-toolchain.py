#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Pre-populate a shared toolchain volume for fast server spawns.

This script is used by `./nukelabctl cache-toolchain <image>` to copy a
toolchain image into the shared named volume that the backend mounts at
server spawn time. Running it before any user spawn guarantees that the
first spawn on a node is fast.

It mirrors the backend driver's semantics so CLI and spawner never fight
over the same volume: population is serialized with a lock container, the
volume carries a stamp recording which image content it holds (a re-pushed
tag invalidates the cache), and re-population wipes stale content first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime

# Import the canonical volume naming helper from the backend package.
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend")
sys.path.insert(0, _BACKEND_DIR)

from app.services.volume_service import make_toolchain_volume_name  # noqa: E402

_LOCK_TIMEOUT = 15 * 60  # seconds; also the stale-lock age
_LOCK_POLL_INTERVAL = 2.0  # seconds
_TOOLCHAIN_TARGET = "/toolchain-target"
_MANIFEST_FILE = "nukelab-toolchain.json"
_STAMP_FILE = ".nukelab-toolchain-stamp.json"


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


def _image_info(engine: str, image: str) -> dict | None:
    """Return the engine's image inspect dict (Id, RepoDigests), or None."""
    result = _run(engine, "image", "inspect", image, check=False, capture=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError, KeyError):
        return None


def _image_ids_match(a: str | None, b: str | None) -> bool:
    """Compare image IDs across engine formats.

    Docker reports ``sha256:<hex>`` while podman may report the bare hex
    digest; comparing only the digest portion keeps the stamp check valid
    when this CLI and the backend run on different engines.
    """
    if not a or not b:
        return False
    return a.rsplit(":", 1)[-1] == b.rsplit(":", 1)[-1]


def _parse_timestamp(value: str | None) -> float | None:
    """Parse a Docker/Podman RFC3339 timestamp to epoch seconds, or None."""
    if not value:
        return None
    try:
        # Truncate nanoseconds; fromisoformat handles at most microseconds
        # reliably across the Python versions this script may run under.
        value = value.replace("Z", "+00:00")
        if "." in value:
            head, tail = value.split(".", 1)
            frac = ""
            for ch in tail:
                if ch.isdigit():
                    frac += ch
                else:
                    break
            rest = tail[len(frac):]
            value = f"{head}.{frac[:6]}{rest}"
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def _lock_name(volume_name: str) -> str:
    digest = hashlib.sha256(volume_name.encode("utf-8")).hexdigest()[:12]
    return f"nukelab-toolchain-lock-{digest}"


def _acquire_lock(engine: str, image: str, volume_name: str) -> str:
    """Acquire the cross-process populate lock; returns the lock name.

    The engine's atomic container-name creation is the semaphore: creating
    the lock container (never started) succeeds for exactly one caller, which
    also covers concurrent backend spawns using the same pattern. Lock
    containers older than the timeout are stale (a crashed populate) and are
    force-removed before retrying.
    """
    lock_name = _lock_name(volume_name)
    deadline = time.monotonic() + _LOCK_TIMEOUT
    while True:
        result = _run(
            engine,
            "create",
            "--name",
            lock_name,
            "--label",
            "nukelab.managed=true",
            "--label",
            f"nukelab.toolchain.lock={volume_name}",
            image,
            "true",
            check=False,
            capture=True,
        )
        if result.returncode == 0:
            return lock_name

        if time.monotonic() > deadline:
            raise RuntimeError(f"Timed out waiting for toolchain lock {lock_name}")

        inspect = _run(engine, "container", "inspect", lock_name, check=False, capture=True)
        if inspect.returncode != 0:
            continue  # Lock disappeared; retry immediately.
        try:
            info = json.loads(inspect.stdout)[0]
            created = _parse_timestamp(info.get("Created") or info.get("CreatedAt"))
        except (json.JSONDecodeError, IndexError, KeyError):
            created = None
        if created is not None and time.time() - created > _LOCK_TIMEOUT:
            print(f"Removing stale toolchain lock container {lock_name}")
            _run(engine, "rm", "-f", lock_name, check=False, capture=True)
            continue
        time.sleep(_LOCK_POLL_INTERVAL)


def _release_lock(engine: str, lock_name: str) -> None:
    _run(engine, "rm", "-f", lock_name, check=False, capture=True)


def _read_manifest_and_stamp(engine: str, image: str, volume_name: str) -> tuple[dict, dict] | None:
    """Read the toolchain manifest and population stamp from the volume.

    Returns (manifest, stamp) when both parse, or None when either is missing
    or invalid (unpopulated or stale volume). The helper container is
    hardened the same way as the backend driver's.
    """
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
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--read-only",
            image,
            "sh",
            "-c",
            f"cat /opt/nuke/{_MANIFEST_FILE}"
            " && printf '\\n---\\n'"
            f" && cat /opt/nuke/{_STAMP_FILE}",
            check=False,
            capture=True,
        )
        if result.returncode != 0:
            return None
        manifest_text, sep, stamp_text = result.stdout.partition("\n---\n")
        if not sep:
            return None
        return json.loads(manifest_text), json.loads(stamp_text)
    except (json.JSONDecodeError, OSError):
        return None


def _populate(engine: str, image: str, volume_name: str, mount_paths: list[str], image_info: dict) -> None:
    """Wipe and (re)populate the shared volume, then write the stamp."""
    stamp = json.dumps(
        {
            "image_id": image_info.get("Id"),
            "repo_digests": image_info.get("RepoDigests") or [],
            "populated_at": datetime.now(UTC).isoformat(),
        }
    )
    copy_script = f"rm -rf {_TOOLCHAIN_TARGET}/* {_TOOLCHAIN_TARGET}/.[!.]*; "
    # Contents go to the volume root: consumers mount the volume at the mount
    # path (e.g. /opt/nuke) and must see the toolchain tree directly.
    for path in mount_paths:
        copy_script += f"cp -a {path}/. {_TOOLCHAIN_TARGET}/; "
    copy_script += f"printf '%s' {shlex.quote(stamp)} > {_TOOLCHAIN_TARGET}/{_STAMP_FILE}"

    _run(
        engine,
        "run",
        "--rm",
        "-v",
        f"{volume_name}:{_TOOLCHAIN_TARGET}",
        "--cap-drop",
        "ALL",
        # cp -a needs these to preserve ownership.
        "--cap-add",
        "CHOWN",
        "--cap-add",
        "FOWNER",
        "--cap-add",
        "DAC_OVERRIDE",
        "--cap-add",
        "SETUID",
        "--cap-add",
        "SETGID",
        "--security-opt",
        "no-new-privileges:true",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=64m",
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
        "--force",
        action="store_true",
        help="Wipe and re-populate the volume even if it is up to date.",
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

    image_info = _image_info(engine, args.image)
    if image_info is None:
        print(f"ERROR: Toolchain image {args.image} is not available locally.", file=sys.stderr)
        return 1
    image_id = image_info.get("Id")

    if not _volume_exists(engine, volume_name):
        print("Creating shared volume...")
        _run(engine, "volume", "create", volume_name)

    if not args.force:
        cached = _read_manifest_and_stamp(engine, args.image, volume_name)
        if cached is not None and _image_ids_match(cached[1].get("image_id"), image_id):
            print("Volume is already populated and up to date; nothing to do.")
            return 0

    lock_name = _acquire_lock(engine, args.image, volume_name)
    try:
        # Re-check after acquiring: another process may have populated while
        # we waited for the lock.
        if not args.force:
            cached = _read_manifest_and_stamp(engine, args.image, volume_name)
            if cached is not None and _image_ids_match(cached[1].get("image_id"), image_id):
                print("Volume was populated while waiting for the lock; nothing to do.")
                return 0

        print("Populating shared volume from image (this may take a while)...")
        _populate(engine, args.image, volume_name, args.mount, image_info)

        cached = _read_manifest_and_stamp(engine, args.image, volume_name)
        if cached is None:
            print("ERROR: Toolchain manifest missing after population.", file=sys.stderr)
            return 1
    finally:
        _release_lock(engine, lock_name)

    print("Shared volume populated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
