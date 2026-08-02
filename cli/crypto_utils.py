"""
Fernet (AES-128-CBC + HMAC-SHA256) encryption utilities for sensitive fields.
The encryption key is derived from SECRET_KEY if ENCRYPTION_KEY is not set.
"""
import os
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    """Return a Fernet instance, creating the key from env vars if needed."""
    raw = os.getenv("ENCRYPTION_KEY")
    if raw:
        key = raw.encode() if isinstance(raw, str) else raw
    else:
        secret = os.getenv("SECRET_KEY", "super-secret-key")
        derived = hashlib.sha256(secret.encode()).digest()
        key = base64.urlsafe_b64encode(derived)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe base64 token."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`."""
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except Exception:
        return ""


def mask(value: str, visible: int = 4) -> str:
    """Return a masked representation, showing only the last *visible* chars."""
    if not value:
        return "—"
    suffix = value[-visible:] if len(value) >= visible else value
    return f"{'*' * 16}{suffix}"


def generate_key() -> str:
    """Generate a fresh Fernet key (for key rotation)."""
    return Fernet.generate_key().decode()
