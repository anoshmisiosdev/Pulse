"""Google Places (New) local competitor discovery."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.competitor_prices.schemas import DiscoveredCompetitor

_TIMEOUT = httpx.Timeout(12.0, connect=5.0)
_BASIC_FIELDS = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.primaryType",
        "places.businessStatus",
    ]
)
_DETAIL_FIELDS = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "websiteUri",
        "nationalPhoneNumber",
        "rating",
        "userRatingCount",
        "businessStatus",
    ]
)
_CATEGORY_TYPES: dict[str, list[str]] = {
    "coffee shop": ["cafe", "coffee_shop"],
    "cafe": ["cafe", "coffee_shop"],
    "restaurant": ["restaurant"],
    "gym": ["gym"],
    "fitness center": ["gym"],
    "hair salon": ["hair_salon"],
    "beauty salon": ["beauty_salon"],
    "boutique": ["clothing_store"],
}


class GooglePlacesError(Exception):
    """Google Places could not return usable competitors."""


class GooglePlacesConfigurationError(GooglePlacesError):
    """Google Places is not configured."""


@dataclass(frozen=True)
class PlacesCallStats:
    requests: int = 0


class GooglePlacesClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.api_key = (
            api_key if api_key is not None else settings.effective_google_maps_api_key
        )
        self.base_url = (base_url or settings.google_places_base_url).rstrip("/")
        self.http_client = http_client
        self.requests_made = 0

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
            raise GooglePlacesConfigurationError(
                "Set GOOGLE_MAPS_SERVER_API_KEY to use Google Places discovery."
            )
        radius_meters = min(radius_miles * 1609.344, 50_000.0)
        category_key = " ".join(business_category.lower().split())
        place_types = _CATEGORY_TYPES.get(category_key)
        count = max(1, min(max_results + 2, 20))
        if place_types:
            endpoint = "places:searchNearby"
            body: dict[str, object] = {
                "includedTypes": place_types,
                "maxResultCount": count,
                "rankPreference": "DISTANCE",
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": latitude, "longitude": longitude},
                        "radius": radius_meters,
                    }
                },
            }
        else:
            endpoint = "places:searchText"
            body = {
                "textQuery": business_category,
                "maxResultCount": count,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": latitude, "longitude": longitude},
                        "radius": radius_meters,
                    }
                },
            }
        data = await self._request("POST", endpoint, json=body, field_mask=_BASIC_FIELDS)
        places = data.get("places") or []
        if not isinstance(places, list):
            raise GooglePlacesError("Google Places returned an unexpected response.")
        basic = [self._parse_place(item) for item in places if isinstance(item, dict)]
        active = [item for item in basic if item is not None]
        enriched: list[DiscoveredCompetitor] = []
        for competitor in active[:count]:
            if not competitor.place_id:
                enriched.append(competitor)
                continue
            try:
                detail = await self._request(
                    "GET",
                    f"places/{competitor.place_id}",
                    field_mask=_DETAIL_FIELDS,
                )
                enriched.append(self._parse_place(detail) or competitor)
            except GooglePlacesError:
                enriched.append(competitor)
        return enriched

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        field_mask: str,
    ) -> dict[str, object]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask,
        }
        try:
            self.requests_made += 1
            if self.http_client is not None:
                response = await self.http_client.request(
                    method, f"{self.base_url}/{path}", headers=headers, json=json
                )
            else:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    response = await client.request(
                        method, f"{self.base_url}/{path}", headers=headers, json=json
                    )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GooglePlacesError(
                f"Google Places request failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise GooglePlacesError("Google Places request failed.") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise GooglePlacesError("Google Places returned an unexpected response.")
        return payload

    @staticmethod
    def _parse_place(item: dict[str, object]) -> DiscoveredCompetitor | None:
        if item.get("businessStatus") == "CLOSED_PERMANENTLY":
            return None
        display = item.get("displayName")
        name = display.get("text") if isinstance(display, dict) else display
        if not isinstance(name, str) or not name.strip():
            return None
        location = item.get("location") if isinstance(item.get("location"), dict) else {}
        return DiscoveredCompetitor(
            name=name.strip(),
            address=str(item.get("formattedAddress") or "") or None,
            website=str(item.get("websiteUri") or "") or None,
            phone=str(item.get("nationalPhoneNumber") or "") or None,
            rating=_optional_float(item.get("rating")),
            reviewCount=_optional_int(item.get("userRatingCount")),
            latitude=_optional_float(location.get("latitude")),
            longitude=_optional_float(location.get("longitude")),
            placeId=str(item.get("id") or "") or None,
            discoveryProvider="google_places",
            relevanceReason="Canonical nearby business returned by Google Places.",
        )


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
