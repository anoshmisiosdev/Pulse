"""Publishing approved posts through Buffer.

Fail-closed throughout. A post reaches Buffer only when the caller explicitly
confirmed, the post is approved, its campaign is active, Buffer is configured,
and the copy passes its platform's limits. Anything short of that is refused
before a request goes out.

Publishing is deliberately **not** retried. A timeout after Buffer has already
accepted the post would, on retry, post it twice — and there is no un-post. A
failed publish is surfaced for a human to look at instead.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.social import SocialCampaign, SocialPost
from app.social.editorial import formatted_length, normalized_hashtags
from app.social.scheduling import as_utc

logger = logging.getLogger("pulse.social.publish")

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
X_MAX_CHARS = 280

_CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess {
      post { id status dueAt externalLink channelId channelService shareMode }
    }
    ... on NotFoundError     { message }
    ... on UnauthorizedError { message }
    ... on UnexpectedError   { message }
    ... on RestProxyError    { message link code }
    ... on LimitReachedError { message }
    ... on InvalidInputError { message }
  }
}
"""


class PublishNotConfigured(RuntimeError):
    """Buffer credentials or channel ids are missing."""


class NothingToPublish(RuntimeError):
    """No post is eligible — not approved, or its campaign is paused."""


@dataclass
class PublishOutcome:
    post_id: str
    ok: bool
    status: str
    message: str
    provider_post_ids: list[str]
    published_url: str | None = None


def _ids(raw: str) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def profile_ids_for(platform: str) -> list[str]:
    specific = (
        settings.buffer_linkedin_profile_ids
        if platform == "linkedin"
        else settings.buffer_x_profile_ids
    )
    return _ids(specific) or _ids(settings.buffer_profile_ids)


def is_configured() -> bool:
    has_channel = bool(
        _ids(settings.buffer_linkedin_profile_ids)
        or _ids(settings.buffer_x_profile_ids)
        or _ids(settings.buffer_profile_ids)
    )
    return bool(settings.buffer_api_key) and has_channel


async def eligible_posts(
    db: AsyncSession, *, business_id: str, post_id: str | None = None
) -> list[SocialPost]:
    """Approved posts whose campaign, if any, is active.

    Pausing a campaign is the kill switch: its posts stay approved and visible
    but stop being publishable, with no state to repair on resume. Posts with no
    campaign are always eligible.
    """
    stmt = (
        select(SocialPost)
        .outerjoin(SocialCampaign, SocialPost.campaign_id == SocialCampaign.id)
        .where(
            SocialPost.business_id == uuid.UUID(business_id),
            SocialPost.status == "approved",
            (SocialPost.campaign_id.is_(None)) | (SocialCampaign.status == "active"),
        )
    )
    if post_id:
        try:
            stmt = stmt.where(SocialPost.id == uuid.UUID(post_id))
        except ValueError:
            return []
    return list((await db.execute(stmt)).scalars())


def _schedule_for(post: SocialPost, mode: str) -> tuple[str, str | None, str]:
    """(buffer mode, dueAt, resulting local status)."""
    if post.scheduled_for:
        due = as_utc(post.scheduled_for)
        if due <= datetime.now(UTC):
            raise ValueError(f"Schedule time is in the past: {due.isoformat()}")
        return "customScheduled", due.isoformat().replace("+00:00", "Z"), "staged"
    if mode == "queue":
        return "addToQueue", None, "staged"
    return "shareNow", None, "posted"


def _validate(post: SocialPost) -> None:
    tags = normalized_hashtags(list(post.hashtags or []))
    if post.platform == "x":
        length = formatted_length(post.post_text, tags)
        if length > X_MAX_CHARS:
            raise ValueError(
                f"Too long for X: {length} characters including hashtags "
                f"(limit {X_MAX_CHARS})."
            )


def _failure_message(payload: dict, status_code: int) -> str:
    node = ((payload.get("data") or {}).get("createPost")) or {}
    if node.get("message"):
        return str(node["message"])
    errors = payload.get("errors") or []
    joined = "; ".join(str(e.get("message")) for e in errors if e.get("message"))
    return joined or f"HTTP {status_code}"


async def publish_post(post: SocialPost, *, mode: str = "now") -> PublishOutcome:
    """Send one approved post to every configured channel for its platform."""
    if not is_configured():
        raise PublishNotConfigured(
            "Connect Buffer and set at least one channel id before publishing."
        )

    channels = profile_ids_for(post.platform)
    if not channels:
        raise PublishNotConfigured(f"No Buffer channel configured for {post.platform}.")

    _validate(post)
    buffer_mode, due_at, target_status = _schedule_for(post, mode)

    tags = normalized_hashtags(list(post.hashtags or []))
    text = post.post_text.strip()
    if tags:
        text = f"{text}\n\n" + " ".join(f"#{t}" for t in tags)

    assets = []
    if post.image_url and post.image_url.startswith(("http://", "https://")):
        assets = [
            {"image": {"url": post.image_url, "metadata": {"altText": post.alt_text or ""}}}
        ]

    headers = {
        "authorization": f"Bearer {settings.buffer_api_key}",
        "content-type": "application/json",
    }

    provider_ids: list[str] = []
    published_url: str | None = None
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for channel_id in channels:
            payload = {
                "channelId": channel_id,
                "text": text,
                "schedulingType": "automatic",
                "mode": buffer_mode,
                "assets": assets,
                "source": "churnary",
                "aiAssisted": True,
                "saveToDraft": False,
            }
            if due_at:
                payload["dueAt"] = due_at
            try:
                resp = await client.post(
                    settings.buffer_api_url,
                    headers=headers,
                    json={"query": _CREATE_POST, "variables": {"input": payload}},
                )
                body = resp.json() if resp.content else {}
            except (httpx.HTTPError, ValueError) as exc:
                failures.append(f"{channel_id}: {exc}")
                continue

            node = ((body.get("data") or {}).get("createPost")) or {}
            if resp.is_success and not body.get("errors") and (
                node.get("__typename") == "PostActionSuccess"
            ):
                created = node.get("post") or {}
                if created.get("id"):
                    provider_ids.append(str(created["id"]))
                published_url = published_url or created.get("externalLink")
            else:
                failures.append(f"{channel_id}: {_failure_message(body, resp.status_code)}")

    if failures:
        return PublishOutcome(
            post_id=str(post.id),
            ok=False,
            status="failed",
            message=f"Buffer rejected {len(failures)} channel(s): " + "; ".join(failures),
            provider_post_ids=provider_ids,
        )

    message = {
        "customScheduled": f"Scheduled with Buffer for {due_at}.",
        "addToQueue": "Added to your Buffer queue.",
        "shareNow": "Sent to Buffer to publish now.",
    }[buffer_mode]
    return PublishOutcome(
        post_id=str(post.id),
        ok=True,
        status=target_status,
        message=message,
        provider_post_ids=provider_ids,
        published_url=published_url,
    )


async def publish_approved(
    db: AsyncSession, *, business_id: str, post_id: str | None = None, mode: str = "now"
) -> list[PublishOutcome]:
    """Publish every eligible post, recording the outcome on each row."""
    posts = await eligible_posts(db, business_id=business_id, post_id=post_id)
    if not posts:
        raise NothingToPublish(
            "That post is not approved or its campaign is paused."
            if post_id
            else "There are no approved posts ready to publish."
        )
    if not is_configured():
        raise PublishNotConfigured(
            "Connect Buffer and set at least one channel id before publishing."
        )

    outcomes: list[PublishOutcome] = []
    for post in posts:
        try:
            outcome = await publish_post(post, mode=mode)
        except (ValueError, PublishNotConfigured) as exc:
            outcome = PublishOutcome(
                post_id=str(post.id), ok=False, status="failed",
                message=str(exc), provider_post_ids=[],
            )
        post.status = outcome.status
        post.provider_post_ids = outcome.provider_post_ids
        post.published_url = outcome.published_url
        post.failure_reason = None if outcome.ok else outcome.message
        if outcome.ok and outcome.status == "posted":
            post.posted_at = datetime.now(UTC)
        logger.info("publish %s -> %s (%s)", post.id, outcome.status, outcome.message)
        outcomes.append(outcome)

    await db.flush()
    return outcomes
