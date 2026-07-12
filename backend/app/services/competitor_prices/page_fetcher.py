"""Bounded, SSRF-protected retrieval for public pricing evidence pages."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address, ip_address
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from httpx_secure import httpx_ssrf_protection

from app.core.config import settings

_USER_AGENT = "PulsePricingResearch/1.0 (+https://pulse.example)"
_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "application/json")


@dataclass(frozen=True)
class PageFetchResult:
    url: str
    content: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    retrieved_at: datetime | None = None
    content_hash: str | None = None
    error: str | None = None
    robots_allowed: bool = True

    @property
    def succeeded(self) -> bool:
        return self.content is not None and self.status_code is not None


class SafePageFetcher:
    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self.http_client = http_client
        self.requests_made = 0

    async def fetch(self, url: str) -> PageFetchResult:
        validation_error = _validate_public_url(url)
        if validation_error:
            return PageFetchResult(url=url, error=validation_error)

        raw_client = self.http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.source_fetch_timeout_seconds, connect=5.0),
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        )
        client = raw_client if self.http_client is not None else httpx_ssrf_protection(
            raw_client,
            custom_validator=_public_ip_and_port,
        )
        try:
            if not await self._robots_allows(client, url):
                return PageFetchResult(
                    url=url,
                    error="Source disallows automated retrieval via robots.txt.",
                    robots_allowed=False,
                )
            return await self._fetch_with_redirects(client, url)
        except httpx.HTTPError:
            return PageFetchResult(url=url, error="Source retrieval failed.")
        except Exception:
            return PageFetchResult(url=url, error="Source retrieval was blocked for safety.")
        finally:
            if self.http_client is None:
                await raw_client.aclose()

    async def _robots_allows(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            result = await self._request_limited(
                client,
                robots_url,
                max_bytes=256_000,
                allowed_content_types=("text/plain", "text/html"),
                max_redirects=1,
            )
        except httpx.HTTPError:
            return True
        if result.status_code in {401, 403}:
            return False
        if not result.succeeded or not result.content:
            return True
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(result.content.splitlines())
        return parser.can_fetch(_USER_AGENT, url)

    async def _fetch_with_redirects(
        self, client: httpx.AsyncClient, url: str
    ) -> PageFetchResult:
        return await self._request_limited(
            client,
            url,
            max_bytes=settings.source_fetch_max_bytes,
            allowed_content_types=_ALLOWED_CONTENT_TYPES,
            max_redirects=settings.source_fetch_max_redirects,
        )

    async def _request_limited(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        max_bytes: int,
        allowed_content_types: tuple[str, ...],
        max_redirects: int,
    ) -> PageFetchResult:
        current = url
        for redirect_index in range(max_redirects + 1):
            validation_error = _validate_public_url(current)
            if validation_error:
                return PageFetchResult(url=current, error=validation_error)
            self.requests_made += 1
            request = client.build_request("GET", current)
            response = await client.send(request, stream=True)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect_index >= max_redirects:
                        return PageFetchResult(
                            url=current, error="Source redirected too many times."
                        )
                    location = response.headers.get("location")
                    if not location:
                        return PageFetchResult(
                            url=current, error="Source returned an invalid redirect."
                        )
                    current = urljoin(current, location)
                    continue
                if response.status_code in {403, 429}:
                    return PageFetchResult(
                        url=current,
                        status_code=response.status_code,
                        error=(
                            f"Source returned HTTP {response.status_code}; "
                            "no bypass was attempted."
                        ),
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    return PageFetchResult(
                        url=current,
                        status_code=response.status_code,
                        error=f"Source returned HTTP {response.status_code}.",
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if not any(content_type.startswith(item) for item in allowed_content_types):
                    return PageFetchResult(
                        url=current,
                        status_code=response.status_code,
                        content_type=content_type or None,
                        error="Source content type is not supported.",
                    )
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    return PageFetchResult(
                        url=current,
                        status_code=response.status_code,
                        content_type=content_type,
                        error="Source content exceeded the size limit.",
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return PageFetchResult(
                            url=current,
                            status_code=response.status_code,
                            content_type=content_type,
                            error="Source content exceeded the size limit.",
                        )
                    chunks.append(chunk)
                raw = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                content = raw.decode(encoding, errors="replace")
                return PageFetchResult(
                    url=current,
                    content=content,
                    status_code=response.status_code,
                    content_type=content_type,
                    retrieved_at=datetime.now(UTC),
                    content_hash=hashlib.sha256(raw).hexdigest(),
                )
            finally:
                await response.aclose()
        return PageFetchResult(url=current, error="Source redirected too many times.")


def _validate_public_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "Source URL is invalid."
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "Only public HTTP and HTTPS source URLs are allowed."
    try:
        port = parsed.port
    except ValueError:
        return "Source URL contains an invalid port."
    if port is not None and port not in {80, 443}:
        return "Source URL port is not allowed."
    if parsed.username or parsed.password:
        return "Source URLs containing credentials are not allowed."
    try:
        literal_ip = ip_address(parsed.hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        return "Source URL resolves to a non-public address."
    return None


def _public_ip_and_port(
    _hostname: str, ip: IPv4Address | IPv6Address, port: int
) -> bool:
    return port in {80, 443} and ip.is_global
