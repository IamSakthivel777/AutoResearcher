"""Geographically coherent, opening-aware itinerary clustering."""

from __future__ import annotations

import math
from datetime import date, timedelta
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from autoresearcher.tools.calculations import GeoPoint, haversine_km


class ItineraryPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    opening_hours: str | None = None
    open_days: list[int] | None = None


class ItineraryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    places: list[ItineraryPlace]
    days: int = Field(ge=1, le=60)
    start_date: date | None = None


class ItineraryDay(BaseModel):
    day: int
    places: list[ItineraryPlace]
    estimated_route_km: float


class Itinerary(BaseModel):
    days: list[ItineraryDay]
    warnings: list[str] = Field(default_factory=list)


_WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")


def _available(place: ItineraryPlace, day_number: int, start_date: date | None) -> bool:
    if place.open_days is not None:
        return day_number in place.open_days
    hours = (place.opening_hours or "").strip()
    if not hours or hours == "24/7" or start_date is None:
        return True
    weekday = _WEEKDAYS[(start_date + timedelta(days=day_number - 1)).weekday()]
    clauses = [item.strip() for item in hours.split(";")]
    explicit = [item for item in clauses if item.startswith(weekday)]
    return not explicit or all("off" not in item.lower() for item in explicit)


def _route_distance(places: list[ItineraryPlace]) -> float:
    return sum(
        haversine_km(
            GeoPoint(latitude=left.latitude, longitude=left.longitude),
            GeoPoint(latitude=right.latitude, longitude=right.longitude),
        )
        for left, right in pairwise(places)
    )


def build_itinerary(
    places: list[ItineraryPlace | dict[str, object]],
    days: int,
    *,
    start_date: date | None = None,
) -> Itinerary:
    """Cluster places greedily by proximity while respecting declared closed days."""
    inputs = ItineraryInput.model_validate(
        {"places": places, "days": days, "start_date": start_date}
    )
    validated = inputs.places
    days = inputs.days
    start_date = inputs.start_date
    if not validated:
        return Itinerary(
            days=[
                ItineraryDay(day=day, places=[], estimated_route_km=0)
                for day in range(1, days + 1)
            ]
        )

    target_size = math.ceil(len(validated) / days)
    remaining = list(validated)
    day_groups: list[list[ItineraryPlace]] = [[] for _ in range(days)]
    warnings: list[str] = []
    for day_index in range(days):
        day_number = day_index + 1
        available = [place for place in remaining if _available(place, day_number, start_date)]
        if not available:
            continue
        seed = available[0]
        group = [seed]
        remaining.remove(seed)
        while len(group) < target_size:
            candidates = [
                place for place in remaining if _available(place, day_number, start_date)
            ]
            if not candidates:
                break
            last = group[-1]
            closest = min(
                candidates,
                key=lambda place: haversine_km(
                    GeoPoint(latitude=last.latitude, longitude=last.longitude),
                    GeoPoint(latitude=place.latitude, longitude=place.longitude),
                ),
            )
            group.append(closest)
            remaining.remove(closest)
        day_groups[day_index] = group

    for place in list(remaining):
        candidate_days = [
            index
            for index in range(days)
            if _available(place, index + 1, start_date)
        ]
        if not candidate_days:
            warnings.append(f"'{place.name}' is not open on any requested day and was omitted.")
            continue
        chosen = min(candidate_days, key=lambda index: len(day_groups[index]))
        day_groups[chosen].append(place)

    return Itinerary(
        days=[
            ItineraryDay(
                day=index + 1,
                places=group,
                estimated_route_km=round(_route_distance(group), 2),
            )
            for index, group in enumerate(day_groups)
        ],
        warnings=warnings,
    )
