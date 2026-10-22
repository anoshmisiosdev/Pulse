"""The in-product assistant: tools, the agent loop, degradation, and the API.

The model is stubbed by a scripted responder, so these tests pin the loop's
*behaviour* - which tools run, what happens to bad output, what it refuses to
do - rather than Claude's prose.

The properties worth breaking a build over:
  * a tool never reads another tenant's rows;
  * the assistant has no way to send a message;
  * an unreachable model degrades to a useful answer, not an error.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.billing.limits import evaluate
from app.chat import intents
from app.chat.agent import MAX_STEPS, answer
from app.chat.tools import TOOLS, ToolContext, dispatch
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.llm import LLMError
from app.main import app, fastapi_app
from app.models import (
    Business,
    Campaign,
    CampaignSend,
    ChatConversation,
    ChatMessage,
    CompanyContextItem,
    Customer,
    GenerationLog,
    RecoveryAttribution,
    Subscription,
    Transaction,
    Visit,
)

BUSINESS_ID = uuid.uuid4()
OTHER_BUSINESS_ID = uuid.uuid4()


def _user(business_id: uuid.UUID = BUSINESS_ID) -> CurrentUser:
    return CurrentUser(
        user_id="u1",
        email="owner@hayward.coffee",
        business_id=str(business_id),
        business_name="Hayward Coffee Co.",
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No Bedrock. Retrieval degrades the way it does in production."""
    from app.services.rag.embeddings import EmbeddingError

    async def _no_embeddings(*_a, **_k):
        raise EmbeddingError("no embeddings in tests")

    monkeypatch.setattr("app.services.rag.knowledge_store.embed_query", _no_embeddings)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def _ok(*_a, **_k):
        from app.services import senders

        return senders.SendResult(ok=True, provider_message_id="p1")

    monkeypatch.setattr("app.services.automations.send_email", _ok)
    monkeypatch.setattr("app.services.automations.send_sms", _ok)
    monkeypatch.setattr("app.services.automations.is_quiet_hours", lambda *_a, **_k: False)

    async def _batch(contexts):
        from app.campaigns.generator import GeneratedCopy

        return [
            GeneratedCopy(
                body=f"Hi {c.customer_name}, come back!",
                subject=None if c.channel == "sms" else "We miss you",
                generated_by="claude",
                model="test-model",
            )
            for c in contexts
        ]

    monkeypatch.setattr("app.campaigns.manual.generate_campaigns_batch", _batch)


def script(*responses: str):
    """A stub ``complete_text`` that returns the given strings in order.

    Returns a callable to install plus the list of prompts it was given, so a
    test can assert on what the loop fed back to the model.
    """
    seen: list[str] = []
    remaining = list(responses)

    async def _complete(system: str, user: str, max_tokens: int = 0) -> str:
        seen.append(user)
        if not remaining:
            raise AssertionError("the agent asked for more model turns than scripted")
        return remaining.pop(0)

    return _complete, seen


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}", poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(sessions, *, count: int = 3, tier: str = "growth") -> list[str]:
    ids: list[str] = []
    now = datetime.now(UTC).replace(tzinfo=None)
    async with sessions() as db:
        db.add(Business(id=BUSINESS_ID, name="Hayward Coffee Co.", vertical="cafe"))
        db.add(Subscription(business_id=BUSINESS_ID, tier=tier, status="active"))
        for i in range(count):
            customer = Customer(
                business_id=BUSINESS_ID,
                source="csv",
                first_name=f"Cust{i}",
                last_name="Example",
                email=f"cust{i}@example.com",
                phone=f"+1555000{i:04d}",
            )
            db.add(customer)
            await db.flush()
            ids.append(str(customer.id))
            for week in range(8):
                db.add(
                    Visit(
                        business_id=BUSINESS_ID,
                        customer_id=customer.id,
                        source="csv",
                        occurred_at=now - timedelta(days=45 + week * 7),
                    )
                )
            db.add(
                Transaction(
                    business_id=BUSINESS_ID,
                    customer_id=customer.id,
                    source="csv",
                    amount=60,
                    occurred_at=now - timedelta(days=45),
                )
            )
        await db.commit()
    return ids


async def _ctx(sessions, *, business_id=BUSINESS_ID, tier="growth") -> ToolContext:
    async with sessions() as db:
        yield_ctx = ToolContext(
            db=db,
            user=_user(business_id),
            entitlements=evaluate(
                tier_name=tier, status="active", customer_count=0, integration_count=0
            ),
        )
        return yield_ctx


# -- Tools: tenant scoping ----------------------------------------------------


async def test_at_risk_customers_only_sees_this_tenant(sessions):
    """The tenant boundary is a WHERE clause, not a prompt instruction."""
    await _seed(sessions, count=2)
    now = datetime.now(UTC).replace(tzinfo=None)
    async with sessions() as db:
        db.add(Business(id=OTHER_BUSINESS_ID, name="Rival Salon", vertical="salon"))
        theirs = Customer(
            business_id=OTHER_BUSINESS_ID,
            source="csv",
            first_name="Secret",
            last_name="Person",
            email="secret@rival.com",
        )
        db.add(theirs)
        await db.flush()
        db.add(
            Visit(
                business_id=OTHER_BUSINESS_ID,
                customer_id=theirs.id,
                source="csv",
                occurred_at=now - timedelta(days=60),
            )
        )
        await db.commit()

    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        result = await dispatch(ctx, "get_at_risk_customers", {"limit": 25})

    names = [c["name"] for c in result["customers"]]
    assert "Secret Person" not in names
    assert len(names) == 2


async def test_find_customer_cannot_reach_another_tenants_person(sessions):
    await _seed(sessions, count=1)
    async with sessions() as db:
        db.add(Business(id=OTHER_BUSINESS_ID, name="Rival", vertical="salon"))
        db.add(
            Customer(
                business_id=OTHER_BUSINESS_ID,
                source="csv",
                first_name="Secret",
                email="secret@rival.com",
            )
        )
        await db.commit()

    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        assert (await dispatch(ctx, "find_customer", {"query": "Secret"}))["matches"] == []


async def test_customer_detail_refuses_a_foreign_id(sessions):
    """Even handed the exact UUID, a tool must not read across tenants."""
    await _seed(sessions, count=1)
    async with sessions() as db:
        db.add(Business(id=OTHER_BUSINESS_ID, name="Rival", vertical="salon"))
        theirs = Customer(business_id=OTHER_BUSINESS_ID, source="csv", email="x@rival.com")
        db.add(theirs)
        await db.commit()
        foreign_id = str(theirs.id)

    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        result = await dispatch(ctx, "get_customer_detail", {"customer_id": foreign_id})
    assert result == {"error": "No such customer."}


async def test_knowledge_search_never_returns_private_brain_records(sessions):
    """public_safe is the content gate; the assistant must not route around it."""
    await _seed(sessions, count=1)
    async with sessions() as db:
        db.add(
            CompanyContextItem(
                business_id=BUSINESS_ID,
                title="Public win",
                kind="milestone",
                summary="We opened a second location",
                public_safe=True,
            )
        )
        db.add(
            CompanyContextItem(
                business_id=BUSINESS_ID,
                title="Private location note",
                kind="note",
                summary="Landlord dispute at the second location",
                public_safe=False,
            )
        )
        await db.commit()

    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        result = await dispatch(ctx, "search_business_knowledge", {"query": "location"})

    titles = [row["title"] for row in result["company_brain"]]
    assert "Public win" in titles
    assert "Private location note" not in titles
    assert "Landlord dispute" not in json.dumps(result)


# -- Tools: argument handling --------------------------------------------------


async def test_an_unknown_tool_is_an_error_not_an_exception(sessions):
    await _seed(sessions, count=1)
    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        result = await dispatch(ctx, "__import__", {})
    assert "isn't a tool" in result["error"]


async def test_tool_arguments_from_a_model_are_coerced_and_bounded(sessions):
    """Arguments come from a language model, so they're never trusted."""
    await _seed(sessions, count=3)
    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        huge = await dispatch(ctx, "get_at_risk_customers", {"limit": 9_999_999})
        nonsense = await dispatch(ctx, "get_at_risk_customers", {"limit": "lots"})
        bad_id = await dispatch(ctx, "get_customer_detail", {"customer_id": "'; DROP TABLE--"})

    assert huge["showing"] <= 25
    assert nonsense["showing"] <= 25
    assert "error" in bad_id


async def test_recovery_stats_can_be_windowed(sessions):
    ids = await _seed(sessions, count=2)
    async with sessions() as db:
        db.add(
            RecoveryAttribution(
                business_id=BUSINESS_ID,
                customer_id=uuid.UUID(ids[0]),
                estimated_value=400,
                recovered_at=datetime.now(UTC) - timedelta(days=3),
            )
        )
        db.add(
            RecoveryAttribution(
                business_id=BUSINESS_ID,
                customer_id=uuid.UUID(ids[1]),
                estimated_value=250,
                recovered_at=datetime.now(UTC) - timedelta(days=200),
            )
        )
        await db.commit()

    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        recent = await dispatch(ctx, "get_recovery_stats", {"days": 30})
        all_time = await dispatch(ctx, "get_recovery_stats", {})

    assert recent == {
        "window_days": 30,
        "customers_recovered": 1,
        "revenue_recovered": 400.0,
    }
    assert all_time["customers_recovered"] == 2
    assert all_time["revenue_recovered"] == 650.0


# -- The assistant cannot send ------------------------------------------------


def test_no_tool_can_deliver_a_message():
    """Structural guarantee: a chat box that could text 400 people on a misread
    sentence would be the most dangerous surface in the product."""
    assert [name for name, spec in TOOLS.items() if spec.writes] == ["draft_campaign"]
    forbidden = ("send", "deliver", "dispatch", "approve", "publish")
    assert not [
        name for name in TOOLS if any(word in name for word in forbidden)
    ]


async def test_draft_campaign_queues_for_approval_and_sends_nothing(sessions):
    ids = await _seed(sessions, count=2)
    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        result = await dispatch(
            ctx, "draft_campaign", {"customer_ids": ids, "channel": "email"}
        )
        await db.commit()

    assert result["awaiting_approval"] is True
    assert result["drafted_for"] == 2
    async with sessions() as db:
        sends = (await db.execute(select(CampaignSend))).scalars().all()
    assert len(sends) == 2
    assert {s.status for s in sends} == {"pending"}
    assert all(s.sent_at is None for s in sends)


async def test_draft_campaign_respects_the_plan(sessions):
    """SMS on Starter is refused as data, so the model can explain and offer email."""
    ids = await _seed(sessions, count=1, tier="starter")
    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="starter", status="active", customer_count=0, integration_count=0
            ),
        )
        result = await dispatch(ctx, "draft_campaign", {"customer_ids": ids, "channel": "sms"})
    assert result["upgrade_required"] is True
    assert "Upgrade to Growth" in result["error"]


async def test_draft_campaign_rejects_invented_ids(sessions):
    """The model must not be able to message someone by guessing a UUID."""
    await _seed(sessions, count=1)
    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        result = await dispatch(
            ctx, "draft_campaign", {"customer_ids": [str(uuid.uuid4())], "channel": "email"}
        )
        await db.commit()
    assert result["drafted_for"] == 0
    assert result["skipped"]


async def test_draft_campaign_needs_a_list(sessions):
    await _seed(sessions, count=1)
    async with sessions() as db:
        ctx = ToolContext(
            db=db,
            user=_user(),
            entitlements=evaluate(
                tier_name="growth", status="active", customer_count=0, integration_count=0
            ),
        )
        assert "error" in await dispatch(ctx, "draft_campaign", {})
        assert "error" in await dispatch(ctx, "draft_campaign", {"customer_ids": []})


# -- The agent loop -----------------------------------------------------------


async def _agent_ctx(sessions, tier="growth"):
    db = sessions()
    session = await db.__aenter__()
    return session, ToolContext(
        db=session,
        user=_user(),
        entitlements=evaluate(
            tier_name=tier, status="active", customer_count=0, integration_count=0
        ),
    )


async def test_the_agent_runs_a_tool_then_answers(sessions, monkeypatch):
    await _seed(sessions, count=3)
    complete, prompts = script(
        '{"tool": "get_at_risk_customers", "args": {"limit": 3}}',
        '{"reply": "Three customers are slipping away. Cust0 is the most urgent."}',
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="Who's about to leave?")
    finally:
        await session.close()

    assert reply.generated_by == "claude"
    assert reply.text.startswith("Three customers")
    assert [c.tool for c in reply.tool_calls] == ["get_at_risk_customers"]
    assert reply.steps == 2
    # The second prompt must actually contain the tool output, or the model is
    # answering from nothing.
    assert "get_at_risk_customers" in prompts[1]
    assert "Cust0" in prompts[1]


async def test_the_agent_can_chain_find_then_draft(sessions, monkeypatch):
    ids = await _seed(sessions, count=2)
    complete, _ = script(
        '{"tool": "find_customer", "args": {"query": "Cust0"}}',
        json.dumps({"tool": "draft_campaign", "args": {"customer_ids": [ids[0]]}}),
        '{"reply": "Drafted one email. It is waiting for your approval."}',
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="Write Cust0 a win-back")
        await session.commit()
    finally:
        await session.close()

    assert [c.tool for c in reply.tool_calls] == ["find_customer", "draft_campaign"]
    assert reply.drafted_campaign_id is not None
    async with sessions() as db:
        sends = (await db.execute(select(CampaignSend))).scalars().all()
    assert [s.status for s in sends] == ["pending"]


async def test_a_hallucinated_tool_name_is_corrected_not_fatal(sessions, monkeypatch):
    await _seed(sessions, count=1)
    complete, prompts = script(
        '{"tool": "delete_all_customers", "args": {}}',
        '{"tool": "get_portfolio_summary", "args": {}}',
        '{"reply": "You have one customer."}',
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="How many customers?")
    finally:
        await session.close()

    assert reply.generated_by == "claude"
    assert reply.text == "You have one customer."
    # The invalid name never became an invocation, and the model was told why.
    assert [c.tool for c in reply.tool_calls] == ["get_portfolio_summary"]
    assert "is not a tool" in prompts[1]


async def test_markdown_fenced_json_is_still_parsed(sessions, monkeypatch):
    """Models wrap JSON in fences however firmly you ask them not to."""
    await _seed(sessions, count=1)
    complete, _ = script('```json\n{"reply": "Hello there."}\n```')
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="Hi")
    finally:
        await session.close()
    assert reply.text == "Hello there."


async def test_running_out_of_steps_answers_from_what_was_gathered(sessions, monkeypatch):
    """A model that keeps calling tools must not loop forever, and the work
    already done must not be thrown away."""
    await _seed(sessions, count=2)
    complete, _ = script(
        *['{"tool": "get_recovery_stats", "args": {}}'] * MAX_STEPS,
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="How are recoveries?")
    finally:
        await session.close()

    assert reply.steps == MAX_STEPS
    assert reply.generated_by == "fallback"
    assert reply.error == "max_steps_reached"
    assert "recovered" in reply.text


async def test_an_unreachable_model_still_answers_the_question(sessions, monkeypatch):
    """Layer 2 of degradation: no model, but the question is recognized, so the
    deterministic responder runs the right tool and templates the answer."""
    await _seed(sessions, count=2)

    async def _down(*_a, **_k):
        raise LLMError("no provider available")

    monkeypatch.setattr("app.chat.agent.complete_text", _down)

    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="Who is at risk of leaving?")
    finally:
        await session.close()

    assert reply.generated_by == "fallback"
    assert "highest-risk customers" in reply.text
    assert [c.tool for c in reply.tool_calls] == ["get_at_risk_customers"]


async def test_an_unreachable_model_and_an_odd_question_says_what_it_can_do(
    sessions, monkeypatch
):
    """Layer 3: better to state the limits than to bluff."""
    await _seed(sessions, count=1)

    async def _down(*_a, **_k):
        raise LLMError("down")

    monkeypatch.setattr("app.chat.agent.complete_text", _down)

    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="What's the capital of France?")
    finally:
        await session.close()

    assert reply.generated_by == "fallback"
    assert "reduced mode" in reply.text


async def test_an_unconfigured_llm_skips_straight_to_the_fallback(sessions, monkeypatch):
    await _seed(sessions, count=1)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "bedrock_chat_model", "")
    monkeypatch.setattr(settings, "token_router_api_key", "")

    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="How much revenue is at risk?")
    finally:
        await session.close()
    assert reply.generated_by == "fallback"
    assert reply.error == "llm_not_configured"


async def test_an_empty_question_gets_a_prompt_not_an_error(sessions):
    await _seed(sessions, count=1)
    session, ctx = await _agent_ctx(sessions)
    try:
        reply = await answer(ctx, question="   ")
    finally:
        await session.close()
    assert "Ask me anything" in reply.text


# -- Intent matching (pure) ---------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("who's about to leave?", "get_at_risk_customers"),
        ("show me high-risk people", "get_at_risk_customers"),
        ("how many customers came back?", "get_recovery_stats"),
        ("how much have we saved", "get_recovery_stats"),
        ("what campaigns have I sent", "list_recent_campaigns"),
        ("how many customers do I have", "get_portfolio_summary"),
        ("what is our brand voice", "search_business_knowledge"),
    ],
)
def test_intent_matching_covers_the_common_questions(question, expected):
    matched = intents.match(question)
    assert matched is not None
    assert matched.tool == expected


def test_every_suggestion_the_product_offers_is_answerable_offline():
    """The chat shows suggestion chips. If the deterministic fallback can't
    match one of them, an owner who clicks it while the model is down gets
    "I'm in reduced mode" for a question the product just invited them to ask.
    """
    from app.api.chat import _SUGGESTIONS

    unmatched = [s for s in _SUGGESTIONS if intents.match(s) is None]
    assert unmatched == []


@pytest.mark.parametrize(
    "question",
    [
        "Who is about to stop coming in?",
        "who stopped coming in",
        "anyone not coming back?",
        "who's slipping away",
        "who do i call today",
        "who needs attention",
    ],
)
def test_natural_phrasings_of_the_at_risk_question_all_match(question):
    matched = intents.match(question)
    assert matched is not None
    assert matched.tool == "get_at_risk_customers"


def test_the_specific_revenue_question_beats_the_broad_at_risk_pattern():
    """"How much revenue is at risk" wants the total, not a list of names."""
    assert intents.match("how much revenue is at risk").tool == "get_portfolio_summary"
    assert intents.match("who is at risk").tool == "get_at_risk_customers"


def test_a_drafting_request_answers_with_the_list_and_says_where_to_go():
    """The pure path can't supply customer ids, so it must move the owner
    forward rather than refuse."""
    matched = intents.match("Draft a win-back email for my highest-risk customers")
    assert matched is not None
    assert matched.tool == "get_at_risk_customers"
    assert matched.note and "open Campaigns" in matched.note


def test_recovery_questions_win_over_the_broader_at_risk_pattern():
    """Ordering matters: 'how many came back' must not be swallowed by the
    at-risk pattern that also mentions customers."""
    assert intents.match("how many at-risk customers came back?").tool == "get_recovery_stats"


def test_an_unrecognized_question_matches_nothing():
    assert intents.match("what's the weather") is None
    assert intents.match("") is None


def test_rendering_handles_an_empty_result_without_pretending():
    assert "no customer data" in intents.render("get_portfolio_summary", {"status": "no_data"})
    assert intents.render("get_at_risk_customers", {"customers": []}).startswith("Nobody")
    assert intents.render("get_recovery_stats", {"customers_recovered": 0}).startswith("No")


def test_rendering_surfaces_a_tool_error_verbatim():
    assert intents.render("anything", {"error": "Nope."}) == "Nope."


# -- API ----------------------------------------------------------------------


@pytest.fixture
async def client(sessions):
    async def _db():
        async with sessions() as session:
            yield session
            await session.commit()

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = lambda: _user()
    yield TestClient(app)
    fastapi_app.dependency_overrides.clear()


async def test_asking_creates_a_conversation_and_persists_both_turns(
    client, sessions, monkeypatch
):
    await _seed(sessions, count=2)
    complete, _ = script(
        '{"tool": "get_portfolio_summary", "args": {}}',
        '{"reply": "You have 2 customers and both are drifting."}',
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    body = client.post("/api/chat/ask", json={"message": "How are we doing?"}).json()
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"].startswith("You have 2 customers")
    assert body["message"]["tool_calls"][0]["tool"] == "get_portfolio_summary"
    assert body["message"]["tool_calls"][0]["summary"]

    detail = client.get(f"/api/chat/conversations/{body['conversation_id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["title"] == "How are we doing?"


async def test_a_follow_up_carries_the_earlier_turns(client, sessions, monkeypatch):
    await _seed(sessions, count=1)
    complete, prompts = script(
        '{"reply": "Cust0 is your riskiest."}',
        '{"reply": "Because they have not visited in 45 days."}',
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    first = client.post("/api/chat/ask", json={"message": "Who is riskiest?"}).json()
    client.post(
        "/api/chat/ask",
        json={"message": "Why?", "conversation_id": first["conversation_id"]},
    )
    assert "Cust0 is your riskiest." in prompts[1]
    assert "Who is riskiest?" in prompts[1]


async def test_every_chat_turn_is_written_to_the_generation_log(client, sessions, monkeypatch):
    await _seed(sessions, count=1)
    complete, _ = script('{"reply": "Hello."}')
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    client.post("/api/chat/ask", json={"message": "Hi"})
    async with sessions() as db:
        logs = (
            (await db.execute(select(GenerationLog).where(GenerationLog.purpose == "chat_reply")))
            .scalars()
            .all()
        )
    assert len(logs) == 1
    assert logs[0].raw_output == "Hello."
    assert logs[0].user_prompt == "Hi"


async def test_another_tenants_conversation_is_not_readable(client, sessions):
    await _seed(sessions, count=1)
    async with sessions() as db:
        conversation = ChatConversation(business_id=OTHER_BUSINESS_ID, title="Theirs")
        db.add(conversation)
        await db.flush()
        db.add(
            ChatMessage(
                business_id=OTHER_BUSINESS_ID,
                conversation_id=conversation.id,
                role="user",
                content="their secret question",
            )
        )
        await db.commit()
        foreign_id = str(conversation.id)

    assert client.get(f"/api/chat/conversations/{foreign_id}").status_code == 404
    assert client.delete(f"/api/chat/conversations/{foreign_id}").status_code == 404
    assert client.post(
        "/api/chat/ask", json={"message": "hi", "conversation_id": foreign_id}
    ).status_code == 404
    assert client.get("/api/chat/conversations").json() == []


async def test_a_malformed_conversation_id_is_a_404(client, sessions):
    await _seed(sessions, count=1)
    assert client.get("/api/chat/conversations/not-a-uuid").status_code == 404


async def test_deleting_a_conversation_removes_its_messages(client, sessions, monkeypatch):
    await _seed(sessions, count=1)
    complete, _ = script('{"reply": "Hi."}')
    monkeypatch.setattr("app.chat.agent.complete_text", complete)
    body = client.post("/api/chat/ask", json={"message": "Hello"}).json()

    assert client.delete(f"/api/chat/conversations/{body['conversation_id']}").status_code == 204
    async with sessions() as db:
        assert (await db.execute(select(ChatMessage))).scalars().all() == []


async def test_the_conversation_list_reports_message_counts(client, sessions, monkeypatch):
    await _seed(sessions, count=1)
    complete, _ = script('{"reply": "One."}', '{"reply": "Two."}')
    monkeypatch.setattr("app.chat.agent.complete_text", complete)
    first = client.post("/api/chat/ask", json={"message": "First"}).json()
    client.post(
        "/api/chat/ask", json={"message": "Second", "conversation_id": first["conversation_id"]}
    )

    rows = client.get("/api/chat/conversations").json()
    assert len(rows) == 1
    assert rows[0]["message_count"] == 4


async def test_a_long_question_becomes_a_truncated_title(client, sessions, monkeypatch):
    await _seed(sessions, count=1)
    complete, _ = script('{"reply": "Sure."}')
    monkeypatch.setattr("app.chat.agent.complete_text", complete)
    long_question = "Tell me in detail about " + "every single customer " * 10
    body = client.post("/api/chat/ask", json={"message": long_question}).json()
    title = client.get(f"/api/chat/conversations/{body['conversation_id']}").json()["title"]
    assert len(title) <= 58
    assert title.endswith("…")


async def test_an_empty_message_is_rejected_by_validation(client, sessions):
    await _seed(sessions, count=1)
    assert client.post("/api/chat/ask", json={"message": ""}).status_code == 422


async def test_drafting_from_chat_links_the_campaign(client, sessions, monkeypatch):
    ids = await _seed(sessions, count=2)
    complete, _ = script(
        json.dumps({"tool": "draft_campaign", "args": {"customer_ids": ids}}),
        '{"reply": "Two emails are waiting for your approval."}',
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    body = client.post("/api/chat/ask", json={"message": "Draft win-backs"}).json()
    assert body["drafted_campaign_id"]
    campaign = client.get(f"/api/campaigns/{body['drafted_campaign_id']}").json()
    assert campaign["status"] == "pending_approval"
    assert campaign["stats"]["pending"] == 2
    assert campaign["stats"]["sent"] == 0


async def test_the_stream_endpoint_emits_tool_and_message_events(
    client, sessions, monkeypatch
):
    await _seed(sessions, count=2)
    complete, _ = script(
        '{"tool": "get_portfolio_summary", "args": {}}',
        '{"reply": "Two customers, both drifting."}',
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)

    with client.stream("POST", "/api/chat/stream", json={"message": "Status?"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        payload = "".join(resp.iter_text())

    assert "event: status" in payload
    assert "event: tool" in payload
    assert "event: message" in payload
    assert "Two customers, both drifting." in payload


async def test_suggestions_are_offered_for_an_empty_chat(client, sessions):
    await _seed(sessions, count=1)
    body = client.get("/api/chat/suggestions").json()
    assert len(body["suggestions"]) >= 3
    assert any("risk" in s.lower() for s in body["suggestions"])


async def test_an_unknown_campaign_reference_does_not_leak_through_chat(
    client, sessions, monkeypatch
):
    """list_recent_campaigns is scoped too - another tenant's campaign names
    must not appear in an answer."""
    await _seed(sessions, count=1)
    async with sessions() as db:
        db.add(
            Campaign(
                business_id=OTHER_BUSINESS_ID,
                name="Rival secret promo",
                channel="email",
                status="sent",
            )
        )
        await db.commit()

    complete, prompts = script(
        '{"tool": "list_recent_campaigns", "args": {}}',
        '{"reply": "You have no campaigns yet."}',
    )
    monkeypatch.setattr("app.chat.agent.complete_text", complete)
    client.post("/api/chat/ask", json={"message": "What campaigns have I run?"})
    assert "Rival secret promo" not in prompts[1]
