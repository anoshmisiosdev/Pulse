"""Svix signature verification (used to authenticate Resend's webhook)."""

from __future__ import annotations

import base64
import hashlib
import hmac

from app.services.webhooks import verify_svix_signature

SECRET = "whsec_" + base64.b64encode(b"test-signing-key-32-bytes-long!!").decode()


def _sign(secret: str, payload: bytes, svix_id: str, svix_timestamp: str) -> str:
    raw_secret = secret.split("_", 1)[1]
    key = base64.b64decode(raw_secret)
    signed_content = f"{svix_id}.{svix_timestamp}.".encode() + payload
    sig = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()
    return f"v1,{sig}"


def test_valid_signature_verifies():
    payload = b'{"type":"email.opened"}'
    svix_id, ts = "msg_123", "1750000000"
    sig = _sign(SECRET, payload, svix_id, ts)
    assert verify_svix_signature(
        SECRET, payload, svix_id=svix_id, svix_timestamp=ts, svix_signature=sig, now=1750000000
    )


def test_wrong_secret_rejected():
    payload = b'{"type":"email.opened"}'
    svix_id, ts = "msg_123", "1750000000"
    sig = _sign(SECRET, payload, svix_id, ts)
    other_secret = "whsec_" + base64.b64encode(b"a-completely-different-key-here").decode()
    assert not verify_svix_signature(
        other_secret,
        payload,
        svix_id=svix_id,
        svix_timestamp=ts,
        svix_signature=sig,
        now=1750000000,
    )


def test_tampered_payload_rejected():
    payload = b'{"type":"email.opened"}'
    svix_id, ts = "msg_123", "1750000000"
    sig = _sign(SECRET, payload, svix_id, ts)
    tampered = b'{"type":"email.bounced"}'
    assert not verify_svix_signature(
        SECRET, tampered, svix_id=svix_id, svix_timestamp=ts, svix_signature=sig, now=1750000000
    )


def test_expired_timestamp_rejected():
    payload = b'{"type":"email.opened"}'
    svix_id, ts = "msg_123", "1750000000"
    sig = _sign(SECRET, payload, svix_id, ts)
    far_future = 1750000000 + 3600  # 1 hour later, past the 5-minute tolerance
    assert not verify_svix_signature(
        SECRET, payload, svix_id=svix_id, svix_timestamp=ts, svix_signature=sig, now=far_future
    )


def test_missing_fields_rejected():
    assert not verify_svix_signature(
        SECRET, b"{}", svix_id="", svix_timestamp="1750000000", svix_signature="v1,abc"
    )
    assert not verify_svix_signature(
        "", b"{}", svix_id="msg_1", svix_timestamp="1750000000", svix_signature="v1,abc"
    )


def test_multiple_signatures_in_header_one_matches():
    # Svix sends space-separated v1,<sig> candidates when keys are rotated.
    payload = b'{"type":"email.opened"}'
    svix_id, ts = "msg_123", "1750000000"
    real_sig = _sign(SECRET, payload, svix_id, ts)
    header = f"v1,bogus_signature_value {real_sig}"
    assert verify_svix_signature(
        SECRET, payload, svix_id=svix_id, svix_timestamp=ts, svix_signature=header, now=1750000000
    )
