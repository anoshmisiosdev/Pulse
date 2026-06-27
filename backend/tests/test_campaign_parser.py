"""Defensive parsing of model output — the send pipeline must never block on it."""

from __future__ import annotations

import pytest

from app.campaigns.generator import SMS_MAX_CHARS, parse_model_json


def test_clean_email_json():
    copy = parse_model_json('{"subject": "We miss you", "body": "Come back!"}', "email")
    assert copy.subject == "We miss you"
    assert copy.body == "Come back!"


def test_strips_markdown_fences():
    raw = '```json\n{"subject": "Hi", "body": "Hello there"}\n```'
    copy = parse_model_json(raw, "email")
    assert copy.subject == "Hi"
    assert copy.body == "Hello there"


def test_salvages_json_wrapped_in_prose():
    raw = 'Sure! Here you go:\n{"body": "Reply STOP to opt out"}\nHope that helps.'
    copy = parse_model_json(raw, "sms")
    assert copy.body == "Reply STOP to opt out"


def test_sms_is_truncated_to_limit():
    long_body = "x" * 500
    copy = parse_model_json(f'{{"body": "{long_body}"}}', "sms")
    assert len(copy.body) == SMS_MAX_CHARS


def test_email_missing_subject_raises():
    with pytest.raises(ValueError):
        parse_model_json('{"body": "no subject here"}', "email")


def test_missing_body_raises():
    with pytest.raises(ValueError):
        parse_model_json('{"subject": "only subject"}', "email")


def test_malformed_json_raises():
    with pytest.raises(ValueError):
        parse_model_json("not json at all", "sms")


def test_non_object_json_raises():
    with pytest.raises(ValueError):
        parse_model_json("[1, 2, 3]", "sms")
