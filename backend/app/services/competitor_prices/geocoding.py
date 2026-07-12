"""Google address geocoding and deterministic distance calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx

from app.core.config import settings

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class GeocodingError(Exception):
    """The configured geocoder could not resolve an address."""


class GeocodingConfigurationError(GeocodingError):
    """Google Maps geocoding is not configured."""


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float


class GoogleGeocodingClient:
    def __init__(
        self,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.api_key = (
            api_key if api_key is not None else settings.effective_google_maps_api_key
        )
        self.http_client = http_client

    async def geocode(self, address: str) -> Coordinates | None:
        if not self.api_key:
            raise GeocodingConfigurationError(
                "Set GOOGLE_MAPS_API_KEY to verify competitor research distances."
            )
        try:
            if self.http_client is not None:
                response = await self.http_client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"address": address, "key": self.api_key},
                )
            else:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    response = await client.get(
                        "https://maps.googleapis.com/maps/api/geocode/json",
                        params={"address": address, "key": self.api_key},
                    )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GeocodingError(
                f"Google geocoding request failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise GeocodingError("Google geocoding request failed.") from exc

        payload = response.json()
        status = payload.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status != "OK":
            message = payload.get("error_message") or status or "unknown error"
            raise GeocodingError(f"Google geocoding failed: {message}")
        results = payload.get("results") or []
        if not results:
            return None
        location = results[0].get("geometry", {}).get("location", {})
        try:
            return Coordinates(latitude=float(location["lat"]), longitude=float(location["lng"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise GeocodingError("Google geocoding returned invalid coordinates.") from exc


def distance_miles(origin: Coordinates, destination: Coordinates) -> float:
    """Calculate great-circle distance using the haversine formula."""

    earth_radius_miles = 3958.7613
    lat1, lon1, lat2, lon2 = map(
        math.radians,
        [origin.latitude, origin.longitude, destination.latitude, destination.longitude],
    )
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return round(2 * earth_radius_miles * math.asin(math.sqrt(a)), 2)
