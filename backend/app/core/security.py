"""Secrets-at-rest encryption and Supabase JWT verification.

OAuth tokens for integrations are Fernet-encrypted before they touch the DB.
Supabase issues HS256 access tokens we verify with the project JWT secret.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    """Build a Fernet from FERNET_KEY.

    Accepts a proper 32-byte urlsafe-base64 key, or derives one deterministically
    from an arbitrary string so local/dev setups don't have to generate a key.
    """
    key = settings.fernet_key.strip()
    if key:
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError):
            pass  # fall through to derivation
    digest = hashlib.sha256((key or "pulse-dev-insecure-key").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(plaintext: str) -> str:
    """Encrypt an OAuth token (or any secret) for storage at rest."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a value produced by :func:`encrypt_token`."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - defensive
        raise ValueError("Could not decrypt token (wrong FERNET_KEY?)") from exc


def verify_supabase_jwt(token: str) -> dict:
    """Verify a Supabase access token and return its claims.

    Raises ``ValueError`` on any failure so callers map it to a 401.
    """
    import jwt  # local import keeps pyjwt out of the hot import path

    if not settings.supabase_jwt_secret:
        raise ValueError("SUPABASE_JWT_SECRET is not configured")
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
