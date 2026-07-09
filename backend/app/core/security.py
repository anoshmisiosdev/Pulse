"""Secrets-at-rest encryption and Supabase token verification.

OAuth tokens for integrations are Fernet-encrypted before they touch the DB.
Login is handled by Supabase on the frontend; the backend verifies the resulting
Supabase access token (JWT) on each request and derives the tenant from its claims.
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


def encrypt_state(payload: dict) -> str:
    """Sign+encrypt an OAuth ``state`` payload (Fernet embeds the timestamp)."""
    import json

    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def decrypt_state(token: str, max_age_seconds: int = 600) -> dict:
    """Verify and decode an OAuth ``state``; rejects tampered or stale tokens."""
    import json

    try:
        raw = _fernet().decrypt(token.encode(), ttl=max_age_seconds)
        return json.loads(raw)
    except (InvalidToken, ValueError) as exc:
        raise ValueError("Invalid or expired OAuth state") from exc


_jwks_client = None  # cached PyJWKClient for asymmetric Supabase projects


def _jwks_url() -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def verify_supabase_jwt(token: str) -> dict:
    """Verify a Supabase access token and return its claims.

    Supports both HS256 (legacy shared JWT secret) and asymmetric RS256/ES256
    (verified via the project's JWKS endpoint). Raises ``ValueError`` on any
    failure so callers map it to a 401.
    """
    import jwt

    if not settings.supabase_url:
        raise ValueError("Supabase is not configured (SUPABASE_URL)")

    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise ValueError("SUPABASE_JWT_SECRET is required for HS256 tokens")
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        # Asymmetric: fetch (and cache) the project's signing keys.
        global _jwks_client
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(_jwks_url())
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
