"""OpenStreetMap Nominatim place search."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from autoresearcher.errors import ToolError


class PlaceSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    query: str = Field(min_length=2, max_length=500)
    near: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)
    timeout: float = Field(default=15.0, gt=0, le=60)


class PlaceResult(BaseModel):
    """A geocoded place backed by an OpenStreetMap object URL."""

    name: str
    address: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    category: str = "place"
    opening_hours: str | None = None
    source_url: HttpUrl


async def search_places(
    query: str,
    *,
    near: str | None = None,
    limit: int = 5,
    timeout: float = 15.0,
) -> list[PlaceResult]:
    """Find named places through Nominatim and preserve their OpenStreetMap provenance."""
    inputs = PlaceSearchInput(query=query, near=near, limit=limit, timeout=timeout)
    search_query = f"{inputs.query}, {inputs.near}" if inputs.near else inputs.query
    try:
        async with httpx.AsyncClient(
            timeout=inputs.timeout,
            headers={"User-Agent": "AutoResearcher/0.1 research@example.invalid"},
        ) as client:
            response = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": search_query,
                    "format": "jsonv2",
                    "limit": inputs.limit,
                    "addressdetails": 1,
                    "extratags": 1,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ToolError(f"Place search failed ({type(exc).__name__}).") from None

    results: list[PlaceResult] = []
    for item in payload[: inputs.limit]:
        osm_type = {"N": "node", "W": "way", "R": "relation"}.get(
            str(item.get("osm_type", ""))[:1].upper(),
            str(item.get("osm_type", "node")),
        )
        osm_id = item.get("osm_id")
        if not osm_id:
            continue
        extra = item.get("extratags") or {}
        name = item.get("name") or str(item.get("display_name", "Place")).split(",", 1)[0]
        results.append(
            PlaceResult.model_validate(
                {
                    "name": name,
                    "address": item.get("display_name") or name,
                    "latitude": float(item["lat"]),
                    "longitude": float(item["lon"]),
                    "category": item.get("type") or item.get("category") or "place",
                    "opening_hours": extra.get("opening_hours"),
                    "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                }
            )
        )
    return results
