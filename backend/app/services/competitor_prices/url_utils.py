"""Canonical URL identity for pricing evidence.

The canonical form is used only for attribution/deduplication. The original URL
is retained for fetching and display.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}


def canonicalize_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/")

    scheme = parsed.scheme.lower() or "https"
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    if not hostname:
        return raw.rstrip("/")

    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
        ),
        doseq=True,
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def urls_equivalent(left: str, right: str) -> bool:
    return bool(left and right and canonicalize_url(left) == canonicalize_url(right))


def canonical_domain(value: str) -> str:
    canonical = canonicalize_url(value)
    try:
        return (urlsplit(canonical).hostname or "").removeprefix("www.")
    except ValueError:
        return ""
