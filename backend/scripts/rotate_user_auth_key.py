#!/usr/bin/env python3
"""Rotate the active Ed25519 user-auth signing key.

Usage:
    python scripts/rotate_user_auth_key.py [--cleanup]

This script is meant to run inside the backend container where the
``USER_AUTH_SECRETS_DIR`` volume is mounted. It:

1. Loads the current active public key and derives its ``kid``.
2. Generates a fresh Ed25519 key pair.
3. Moves the old active public key to ``user-auth-public-<old_kid>.pem``.
4. Writes new active ``user-auth-private.pem`` and ``user-auth-public.pem``.
5. Secure-deletes the old private key.
6. With ``--cleanup``, removes retired public keys whose grace period has expired.
"""

import argparse
import glob
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Insert the backend source tree so app.config can be imported.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402


def _compute_key_id(public_pem: str) -> str:
    return hashlib.sha256(public_pem.encode("utf-8")).hexdigest()[:16]


def _secure_delete(path: str) -> None:
    """Try to securely delete a file; fall back to normal removal."""
    if not os.path.exists(path):
        return

    # Prefer shred(1) when available.
    if shutil.which("shred"):
        try:
            subprocess.run(["shred", "-u", "-z", "-n", "3", path], check=False)
            return
        except Exception:
            pass

    # Fallback: overwrite with random bytes before unlinking.
    try:
        size = os.path.getsize(path)
        with open(path, "wb") as f:
            f.write(os.urandom(size))
    except Exception:
        pass
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _generate_key_pair(private_path: str, public_path: str) -> None:
    private_key = Ed25519PrivateKey.generate()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Write to temp files and rename for atomicity.
    private_tmp = f"{private_path}.tmp"
    public_tmp = f"{public_path}.tmp"

    with open(private_tmp, "wb") as f:
        f.write(private_pem)
    os.chmod(private_tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0o600

    with open(public_tmp, "wb") as f:
        f.write(public_pem)
    os.chmod(public_tmp, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # 0o644

    os.replace(private_tmp, private_path)
    os.replace(public_tmp, public_path)


def _cleanup_retired_keys(secrets_dir: str, grace_seconds: int) -> int:
    """Remove retired public keys older than the grace period."""
    cutoff = time.time() - grace_seconds
    removed = 0
    pattern = os.path.join(secrets_dir, "user-auth-public-*.pem")
    for path in glob.glob(pattern):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
                print(f"Removed expired retired key: {os.path.basename(path)}")
        except Exception as e:
            print(f"Warning: could not remove {path}: {e}")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate user-auth Ed25519 signing key")
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove retired public keys whose grace period has expired",
    )
    args = parser.parse_args()

    secrets_dir = settings.user_auth_secrets_dir
    private_path = settings.user_auth_private_key_path
    public_path = settings.user_auth_public_key_path

    os.makedirs(secrets_dir, mode=0o700, exist_ok=True)

    # Load current active public key (if any) so we can keep it as a retired key.
    old_kid: str | None = None
    old_public_pem: str | None = None
    if os.path.exists(public_path):
        with open(public_path, "rb") as f:
            old_public_pem = f.read().decode("utf-8")
        old_kid = _compute_key_id(old_public_pem)
        print(f"Current active key id: {old_kid}")

    # Move the old private key aside so we can securely wipe it after generating
    # the replacement. The public key PEM is not sensitive and is preserved below.
    old_private_staging: str | None = None
    if os.path.exists(private_path):
        old_private_staging = os.path.join(secrets_dir, "user-auth-private.pem.rotating")
        os.replace(private_path, old_private_staging)

    # Generate new active key pair.
    _generate_key_pair(private_path, public_path)

    with open(public_path, "rb") as f:
        new_public_pem = f.read().decode("utf-8")
    new_kid = _compute_key_id(new_public_pem)
    print(f"New active key id: {new_kid}")

    # Preserve the old public key for the grace period.
    if old_public_pem and old_kid:
        retired_path = os.path.join(secrets_dir, f"user-auth-public-{old_kid}.pem")
        with open(retired_path, "wb") as f:
            f.write(old_public_pem.encode("utf-8"))
        print(f"Retired old public key as {os.path.basename(retired_path)}")

    # Secure-delete the old private key.
    if old_private_staging:
        _secure_delete(old_private_staging)

    # Cleanup expired retired keys if requested.
    if args.cleanup:
        grace = settings.user_auth_key_rotation_grace_seconds
        removed = _cleanup_retired_keys(secrets_dir, grace)
        print(f"Cleanup complete: removed {removed} expired retired key(s)")

    print("Rotation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
