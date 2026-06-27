"""Secrets-at-rest encryption and session-token signing.

OAuth tokens for integrations are Fernet-encrypted before they touch the DB.
After Convex verifies a login, we mint a short-lived HS256 session JWT carrying the
tenant identity (business_id) that the API verifies on each request.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC

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


def create_session_token(
    *,
    user_id: str,
    business_id: str,
    email: str | None,
    business_name: str = "My Business",
    role: str = "owner",
) -> str:
    """Sign a session JWT after Convex has verified the login (HS256)."""
    from datetime import datetime, timedelta

    import jwt

    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "business_id": business_id,
        "email": email,
        "business_name": business_name,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.auth_jwt_ttl_hours),
        "iss": "pulse",
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm="HS256")


def decode_session_token(token: str) -> dict:
    """Verify a Pulse session token. Raises ``ValueError`` on any failure (-> 401)."""
    import jwt

    try:
        return jwt.decode(token, settings.auth_jwt_secret, algorithms=["HS256"], issuer="pulse")
    except jwt.PyJWTError as exc:
        raise ValueError(f"Invalid session: {exc}") from exc
