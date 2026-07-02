# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Encrypt/decrypt sensitive tokens using Fernet."""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import settings


def _get_fernet() -> Fernet:
    """Derive a Fernet key from JWT_SECRET."""
    # Fernet requires a 32-byte base64-encoded key
    key = hashlib.sha256(settings.jwt_secret.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key)
    return Fernet(fernet_key)


def encrypt_token(token: str) -> str:
    """Encrypt a token string."""
    if not token:
        return ""
    f = _get_fernet()
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a token string."""
    if not encrypted:
        return ""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()
