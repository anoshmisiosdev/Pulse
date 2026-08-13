"""Foursquare Places adapter used by the pricing provider bake-off."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.competitor_prices.schemas import DiscoveredCompetitor


class FoursquarePlacesError(Exception):
    pass


class FoursquarePlacesConfigurationError(FoursquarePlacesError):
    pass


class FoursquarePlacesClient:
    provider_name = "foursquare"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key if api_key is not None else settings.foursquare_api_key
        self.base_url = (base_url or settings.foursquare_base_url).rstrip("/")
        self.http_client = http_client
        self.requests_made = 0
        self.duration_ms_total = 0

    async def discover(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_miles: float,
        business_category: str,
        max_results: int,
    ) -> list[DiscoveredCompetitor]:
        if not self.api_key:
            raise FoursquarePlacesConfigurationError(
                "Set FOURSQUARE_API_KEY to use Foursquare place discovery."
            )
        params = {
            "ll": f"{latitude:.6f},{longitude:.6f}",
            "radius": min(100_000, max(1, round(radius_miles * 1609.344))),
            "query": business_category,
            "limit": min(50, max(1, max_results)),
            "sort": "DISTANCE",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "X-Places-Api-Version": settings.foursquare_api_version,
        }
        started = time.perf_counter()
        self.requests_made += 1
        client = self.http_client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.get(
                f"{self.base_url}/places/search", params=params, headers=headers
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FoursquarePlacesError(f"Foursquare place discovery failed: {exc}") from exc
        finally:
            if self.http_client is None:
                await client.aclose()
            self.duration_ms_total += round((time.perf_counter() - started) * 1000)

        rows = payload.get("results", []) if isinstance(payload, dict) else []
        parsed: list[DiscoveredCompetitor] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            competitor = _parse_place(row, latitude, longitude)
            if competitor:
                parsed.append(competitor)
        return parsed[:max_results]


def _parse_place(
    row: dict[str, Any], origin_latitude: float, origin_longitude: float
) -> DiscoveredCompetitor | None:
    name = str(row.get("name") or "").strip()
    if not name:
        return None
    location = row.get("location") if isinstance(row.get("location"), dict) else {}
    geocodes = row.get("geocodes") if isinstance(row.get("geocodes"), dict) else {}
    main = geocodes.get("main") if isinstance(geocodes.get("main"), dict) else {}
    latitude = _number(row.get("latitude") or main.get("latitude"))
    longitude = _number(row.get("longitude") or main.get("longitude"))
    distance_meters = _number(row.get("distance"))
    distance_miles = distance_meters / 1609.344 if distance_meters is not None else None
    address = str(
        location.get("formatted_address")
        or location.get("formattedAddress")
        or location.get("address")
        or ""
    ).strip() or None
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    review_count = _integer(row.get("review_count") or stats.get("total_ratings"))
    return DiscoveredCompetitor(
        name=name,
        address=address,
        website=str(row.get("website") or "").strip() or None,
        phone=str(row.get("tel") or row.get("telephone") or "").strip() or None,
        rating=_number(row.get("rating")),
        reviewCount=review_count,
        distanceMiles=distance_miles,
        latitude=latitude,
        longitude=longitude,
        relevanceReason="Nearby business returned by Foursquare Places.",
        sourceUrls=[],
        radiusVerified=distance_miles is not None,
        placeId=str(row.get("fsq_place_id") or row.get("fsq_id") or "").strip() or None,
        discoveryProvider="foursquare",
    )


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
