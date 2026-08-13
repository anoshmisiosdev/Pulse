"""Bounded, idempotent waitlist email delivery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.security import encrypt_token
from app.models.waitlist import WaitlistSignup
from app.services import waitlist_leads
from app.services.senders import SendResult, resend_client


async def _signup(db, **overrides) -> WaitlistSignup:
    values = {
        "email": "dana@bluebird.example",
        "name": None,
        "first_touch": {},
        "last_touch": {},
        "assigned_founder": "Aditya Kolekar",
    }
    values.update(overrides)
    signup = WaitlistSignup(**values)
    db.add(signup)
    await db.flush()
    return signup


def test_founder_coded_content_routes_the_lead(monkeypatch):
    monkeypatch.setattr(
        waitlist_leads.settings,
        "waitlist_founder_roster",
        "Soham Dogra,Riyan Anosh,Pranjal Mishra,Aditya Kolekar",
    )

    assigned = waitlist_leads.assign_founder(
        "lead@example.com", "aditya_observation_a"
    )

    assert assigned == "Aditya Kolekar"


def test_non_founder_content_uses_stable_hash_fallback(monkeypatch):
    monkeypatch.setattr(
        waitlist_leads.settings,
        "waitlist_founder_roster",
        "Soham Dogra,Riyan Anosh,Pranjal Mishra,Aditya Kolekar",
    )

    first = waitlist_leads.assign_founder("lead@example.com", "brand_demo_a")
    repeat = waitlist_leads.assign_founder("LEAD@example.com", None)

    assert first == repeat
    assert first in waitlist_leads.settings.waitlist_founder_roster_list


async def test_email_stage_sends_once_with_provider_idempotency_and_unsubscribe(
    db, monkeypatch
):
    signup = await _signup(db)
    calls = []

    async def fake_send(to, subject, text, **kwargs):
        calls.append((to, subject, text, kwargs))
        return SendResult(ok=True, provider_message_id="email_123")

    monkeypatch.setattr(waitlist_leads, "send_email", fake_send)

    first = await waitlist_leads.deliver_email_stage(
        db, signup.id, "confirmation"
    )
    second = await waitlist_leads.deliver_email_stage(
        db, signup.id, "confirmation"
    )

    assert first == {"status": "sent", "stage": "confirmation"}
    assert second == {"status": "already_sent", "stage": "confirmation"}
    assert len(calls) == 1
    _, _, body, options = calls[0]
    assert "That's the whole sequence" in body
    assert "/api/waitlist/unsubscribe?token=" in body
    assert options["idempotency_key"] == f"waitlist/{signup.id}/confirmation"
    assert options["headers"]["List-Unsubscribe"].startswith("<")
    assert signup.confirmation_sent_at is not None
    assert signup.confirmation_provider_message_id == "email_123"


async def test_unsubscribe_token_is_stable_authenticated_and_legacy_compatible(
    db, monkeypatch
):
    monkeypatch.setattr(
        waitlist_leads.settings,
        "fernet_key",
        "QkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkI=",
    )
    signup = await _signup(db)

    first = waitlist_leads.unsubscribe_token(signup)
    second = waitlist_leads.unsubscribe_token(signup)
    first_copy = waitlist_leads._email_copy(signup, "confirmation")
    second_copy = waitlist_leads._email_copy(signup, "confirmation")

    assert first == second
    assert first_copy == second_copy
    assert waitlist_leads.signup_id_from_unsubscribe_token(first) == signup.id

    version, raw_id, signature = first.split(".", 2)
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{version}.{raw_id}.{replacement}{signature[1:]}"
    with pytest.raises(ValueError, match="Invalid waitlist unsubscribe token"):
        waitlist_leads.signup_id_from_unsubscribe_token(tampered)

    legacy = encrypt_token(f"waitlist:{signup.id}")
    assert waitlist_leads.signup_id_from_unsubscribe_token(legacy) == signup.id


async def test_opt_out_blocks_every_remaining_stage(db, monkeypatch):
    signup = await _signup(db, email_opted_out_at=datetime.now(UTC))
    calls = []

    async def fake_send(*args, **kwargs):
        calls.append((args, kwargs))
        return SendResult(ok=True)

    monkeypatch.setattr(waitlist_leads, "send_email", fake_send)

    useful = await waitlist_leads.deliver_email_stage(
        db, signup.id, "useful_followup"
    )
    pilot = await waitlist_leads.deliver_email_stage(
        db, signup.id, "pilot_invitation"
    )

    assert useful["status"] == "opted_out"
    assert pilot["status"] == "opted_out"
    assert calls == []


async def test_delivery_failure_is_retryable_and_does_not_mark_sent(db, monkeypatch):
    signup = await _signup(db)

    async def fail_send(*args, **kwargs):
        return SendResult(ok=False, error="temporary_provider_error")

    monkeypatch.setattr(waitlist_leads, "send_email", fail_send)

    with pytest.raises(
        waitlist_leads.WaitlistEmailDeliveryError,
        match="temporary_provider_error",
    ):
        await waitlist_leads.deliver_email_stage(
            db, signup.id, "useful_followup"
        )

    assert signup.useful_followup_sent_at is None


async def test_missing_signup_is_a_safe_noop(db):
    result = await waitlist_leads.deliver_email_stage(
        db, uuid.uuid4(), "pilot_invitation"
    )
    assert result == {"status": "missing", "stage": "pilot_invitation"}


def test_sequence_queues_only_three_bounded_stages(monkeypatch):
    from app.workers import celery_app

    queued = []
    monkeypatch.setattr(waitlist_leads.settings, "resend_api_key", "configured")
    monkeypatch.setattr(waitlist_leads.settings, "waitlist_email_sequence_enabled", True)
    monkeypatch.setattr(waitlist_leads.settings, "waitlist_followup_delay_days", 3)
    monkeypatch.setattr(waitlist_leads.settings, "waitlist_pilot_invite_delay_days", 7)
    monkeypatch.setattr(
        celery_app.send_waitlist_email,
        "apply_async",
        lambda *, args, countdown: queued.append((args, countdown)),
    )
    signup_id = uuid.uuid4()

    result = waitlist_leads.enqueue_email_sequence(signup_id)

    assert result == {
        "confirmation": True,
        "useful_followup": True,
        "pilot_invitation": True,
    }
    assert queued == [
        ([str(signup_id), "confirmation"], 0),
        ([str(signup_id), "useful_followup"], 3 * 86_400),
        ([str(signup_id), "pilot_invitation"], 7 * 86_400),
    ]


def test_resend_client_forwards_idempotency_and_unsubscribe_headers(monkeypatch):
    import resend

    captured = {}

    def fake_send(params, options=None):
        captured["params"] = params
        captured["options"] = options
        return {"id": "email_456"}

    monkeypatch.setattr(resend.Emails, "send", fake_send)

    result = resend_client._send_sync(
        "lead@example.com",
        "Welcome",
        "Hello",
        idempotency_key="waitlist/signup/confirmation",
        headers={"List-Unsubscribe": "<https://example.com/unsubscribe>"},
    )

    assert result.ok is True
    assert result.provider_message_id == "email_456"
    assert captured["options"] == {
        "idempotency_key": "waitlist/signup/confirmation"
    }
    assert captured["params"]["headers"] == {
        "List-Unsubscribe": "<https://example.com/unsubscribe>"
    }
