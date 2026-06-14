"""Symmetric encryption for credentials at rest.

Secrets (OAuth refresh tokens, service passwords, session cookies) are stored
encrypted with Fernet (AES-128-CBC + HMAC). The key is derived from
FIELD_ENCRYPTION_KEY if set, otherwise from DJANGO_SECRET_KEY, so a stable
SECRET_KEY across redeploys keeps stored secrets readable.
"""

import base64
import hashlib

from django.conf import settings

try:
    from cryptography.fernet import Fernet, InvalidToken

    _AVAILABLE = True
except Exception:  # pragma: no cover - cryptography should be installed
    Fernet = None
    InvalidToken = Exception
    _AVAILABLE = False

_PREFIX = "enc:v1:"


def _fernet():
    raw = (getattr(settings, "FIELD_ENCRYPTION_KEY", "") or settings.SECRET_KEY or "nexus").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt(text: str | None) -> str:
    """Return an encrypted, prefix-tagged string (empty stays empty)."""
    if text in (None, ""):
        return ""
    if not _AVAILABLE:
        return text
    token = _fernet().encrypt(str(text).encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt(value: str | None) -> str:
    """Decrypt a value produced by encrypt(). Plaintext (legacy) passes through."""
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        # Legacy plaintext stored before encryption was introduced.
        return value
    if not _AVAILABLE:
        return ""
    token = value[len(_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""
    except Exception:
        return ""


def is_encrypted(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)
