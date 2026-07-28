"""Engagement-inbox rules — pure functions, so every case is a plain assertion.

The expected strings and counts here are the behaviour ported from Splay; they
are the contract the API and the UI copy are built on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.social.inbox_rules import (
    BrandVoice,
    BriefingItem,
    ContextItem,
    build_suggestion,
    classify,
    rank_context,
    summarize,
)

BRAND = BrandVoice(name="Churnary", positioning="We keep local businesses' customers coming back.")
CONTEXT = [
    ContextItem("Supported data sources", "Churnary connects to Square and Stripe. More soon."),
    ContextItem("Pricing overview", "Plans start at $199 per month with a 14-day trial."),
]


# ── classification ───────────────────────────────────────────────────────────


def test_spam_wins_over_everything_else():
    c = classify("Guaranteed 10,000 followers. Follow me for crypto promotion!")
    assert (c.intent, c.priority, c.risk) == ("spam", "low", "low")
    assert c.recommended_action == "Resolve without replying"


def test_complaint_is_high_risk_and_escalates():
    c = classify("I need a refund. This feels like a scam and I am considering legal action.")
    assert (c.intent, c.sentiment, c.priority, c.risk) == ("complaint", "negative", "high", "high")
    assert c.recommended_action == "Escalate for human review before replying"


def test_sales_lead_beats_the_question_mark_rule():
    c = classify("This looks useful. Can I get a demo for our customer success team?")
    assert c.intent == "sales_lead"


def test_question_without_sales_words_is_a_product_question():
    c = classify("Does this integrate with Stripe, and how quickly could we get started?")
    assert (c.intent, c.risk) == ("product_question", "medium")


def test_praise_is_low_priority():
    praise = classify("Congrats on the launch — the approval-first approach is exactly right.")
    assert praise.intent == "praise"


def test_feedback_is_the_fallback_and_reads_sentiment():
    neutral = classify("We tried something similar and the alerts were too generic to be useful.")
    assert (neutral.intent, neutral.sentiment) == ("feedback", "neutral")
    negative = classify("Solid launch, but the rollout felt rushed.")
    assert (negative.intent, negative.sentiment) == ("feedback", "negative")


def test_classifier_patterns_are_substring_matches_not_word_bounded():
    # "cryptocurrency" contains "crypto", so it trips the spam rule. Inherited
    # behaviour: these patterns have no \b anchors and the fixtures depend on it.
    assert classify("Check out our cryptocurrency guide").intent == "spam"
    # But the spam rule spells out promote/promotion, so "promoting" misses it.
    assert classify("Just promoting our newsletter").intent == "feedback"


# ── context ranking ──────────────────────────────────────────────────────────


def test_rank_context_scores_term_overlap_and_drops_misses():
    ranked = rank_context("Which data sources does this connect to?", CONTEXT)
    assert [i.title for i in ranked] == ["Supported data sources"]


def test_rank_context_ignores_short_words():
    # "the", "and", "for" are under the 4-character floor, so nothing scores.
    assert rank_context("the and for", CONTEXT) == []


# ── drafting ─────────────────────────────────────────────────────────────────


def _draft(comment: str, intent: str, risk: str, variant: str = "standard"):
    return build_suggestion(
        author="Maya Chen", comment=comment, intent=intent, risk=risk,
        brand=BRAND, context=CONTEXT, variant=variant,
    )


def test_high_risk_gets_the_escalation_text_and_ignores_variants():
    standard = _draft("I want a refund, this is fraud", "complaint", "high")
    warmer = _draft("I want a refund, this is fraud", "complaint", "high", "warmer")
    assert "appropriate support channel" in standard.reply
    assert warmer.reply == standard.reply


def test_product_question_quotes_the_top_ranked_fact():
    s = _draft("What data sources are supported?", "product_question", "medium")
    assert s.reply == "Great question, Maya. Churnary connects to Square and Stripe."
    assert s.evidence == ["Supported data sources", "Brand positioning"]


def test_product_question_without_context_refuses_to_guess():
    s = build_suggestion(
        author="Maya Chen", comment="What about zebras?", intent="product_question",
        risk="medium", brand=BRAND, context=CONTEXT,
    )
    assert "do not want to guess" in s.reply


def test_spam_drafts_nothing():
    assert _draft("crypto promotion", "spam", "low").reply == ""


def test_warmer_appends_a_thank_you_but_not_to_an_empty_reply():
    assert _draft("Great work", "praise", "low", "warmer").reply.endswith(
        "Thanks for taking the time to reach out."
    )
    assert _draft("crypto promotion", "spam", "low", "warmer").reply == ""


def test_shorter_replaces_the_draft_wholesale():
    assert _draft("Great work", "praise", "low", "shorter").reply == (
        "Thank you, Maya — we really appreciate it."
    )


def test_evidence_lists_only_what_was_offered_to_the_drafter():
    s = build_suggestion(
        author="Sam", comment="pricing please", intent="sales_lead", risk="low",
        brand=BrandVoice(name="Churnary", positioning=""), context=CONTEXT,
    )
    assert "Brand positioning" not in s.evidence


def test_author_without_a_name_falls_back_to_there():
    s = build_suggestion(
        author="   ", comment="Great work", intent="praise", risk="low",
        brand=BRAND, context=[],
    )
    assert s.reply.startswith("Thank you, there —")


# ── briefing ─────────────────────────────────────────────────────────────────

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


def _item(**kw) -> BriefingItem:
    base = dict(
        intent="feedback", risk="low", status="drafted", comment="", original_post_excerpt=None,
        reply_version=1, suggested_reply="drafted text", created_at=NOW, updated_at=NOW,
    )
    return BriefingItem(**{**base, **kw})


def test_counts_exclude_resolved_items():
    b = summarize(
        [
            _item(intent="sales_lead"),
            _item(intent="sales_lead", status="resolved"),
            _item(risk="high"),
        ],
        today=TODAY,
    )
    assert (b.leads, b.high_risk) == (1, 1)


def test_awaiting_reply_skips_spam():
    items = [_item(intent="spam", status="needs_reply"), _item(status="needs_reply")]
    assert summarize(items, today=TODAY).awaiting_reply == 1


def test_approved_today_uses_the_updated_date():
    stale = _item(status="approved", updated_at=NOW - timedelta(days=2))
    assert summarize([stale], today=TODAY).approved_today == 0
    assert summarize([_item(status="approved")], today=TODAY).approved_today == 1


def test_topics_are_word_bounded_and_tie_break_alphabetically():
    b = summarize(
        [
            _item(comment="Does the API connect to Stripe?"),
            _item(comment="What does pricing look like?"),
        ],
        today=TODAY,
    )
    # One hit each — "Integrations" sorts before "Pricing".
    assert (b.top_topic, b.top_topic_count) == ("Integrations", 1)


def test_topic_matching_includes_the_post_excerpt():
    b = summarize([_item(comment="Nice.", original_post_excerpt="Our new dashboard")], today=TODAY)
    assert b.top_topic == "Analytics"


def test_recommended_action_prefers_risk_then_leads():
    risky = summarize([_item(risk="high"), _item(intent="sales_lead")], today=TODAY)
    assert risky.recommended_action == "Review 1 high-risk conversation before responding."
    leads = summarize([_item(intent="sales_lead"), _item(intent="sales_lead")], today=TODAY)
    assert leads.recommended_action == "Approve replies for 2 prospective customers."


def test_recommended_action_when_the_inbox_is_clear():
    b = summarize([_item(status="resolved")], today=TODAY)
    assert b.recommended_action == "Your priority inbox is clear. Review new audience feedback."


def test_minutes_saved_adds_up_per_activity():
    # 1 classification + 2 drafting + 1 approval = 4
    assert summarize([_item(status="approved")], today=TODAY).estimated_minutes_saved == 4
    # 1 classification + 1 spam triage (no draft) = 2
    spam = _item(intent="spam", status="resolved", reply_version=0, suggested_reply="")
    assert summarize([spam], today=TODAY).estimated_minutes_saved == 2


def test_minutes_saved_only_counts_items_touched_today():
    old = _item(created_at=NOW - timedelta(days=3), updated_at=NOW - timedelta(days=3))
    assert summarize([old], today=TODAY).estimated_minutes_saved == 0


def test_empty_inbox_is_all_zeroes():
    b = summarize([], today=TODAY)
    assert (b.leads, b.top_topic, b.top_topic_count, b.estimated_minutes_saved) == (0, None, 0, 0)
