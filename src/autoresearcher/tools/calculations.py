"""Deterministic travel-time and budget estimation tools."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GeoPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class TravelTimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: GeoPoint
    destination: GeoPoint
    mode: Literal["walk", "bike", "drive", "transit"] = "drive"
    traffic_multiplier: float = Field(default=1.15, ge=1, le=3)


class TravelTimeEstimate(BaseModel):
    distance_km: float = Field(ge=0)
    duration_minutes: int = Field(ge=0)
    mode: str
    is_estimate: bool = True


_SPEED_KMH = {"walk": 4.5, "bike": 15.0, "drive": 28.0, "transit": 22.0}


def haversine_km(left: GeoPoint, right: GeoPoint) -> float:
    """Return great-circle distance between two WGS84 coordinates."""
    radius_km = 6_371.0088
    lat1, lon1 = math.radians(left.latitude), math.radians(left.longitude)
    lat2, lon2 = math.radians(right.latitude), math.radians(right.longitude)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def estimate_travel_time(
    origin: GeoPoint | dict[str, float],
    destination: GeoPoint | dict[str, float],
    *,
    mode: Literal["walk", "bike", "drive", "transit"] = "drive",
    traffic_multiplier: float = 1.15,
) -> TravelTimeEstimate:
    """Estimate point-to-point time using great-circle distance and mode speeds."""
    inputs = TravelTimeInput.model_validate(
        {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "traffic_multiplier": traffic_multiplier,
        }
    )
    distance = haversine_km(inputs.origin, inputs.destination)
    multiplier = inputs.traffic_multiplier if mode in {"drive", "transit"} else 1.0
    duration = round(distance / _SPEED_KMH[mode] * 60 * multiplier)
    return TravelTimeEstimate(
        distance_km=round(distance, 2),
        duration_minutes=max(duration, 1) if distance else 0,
        mode=mode,
    )


class BudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=365)
    travelers: int = Field(default=1, ge=1, le=100)
    accommodation_per_night: float = Field(default=0, ge=0)
    meals_per_person_day: float = Field(default=0, ge=0)
    local_transport_per_person_day: float = Field(default=0, ge=0)
    activities_per_person: float = Field(default=0, ge=0)
    fixed_costs: float = Field(default=0, ge=0)
    contingency_percent: float = Field(default=10, ge=0, le=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class BudgetEstimate(BaseModel):
    currency: str
    accommodation: float
    meals: float
    local_transport: float
    activities: float
    fixed_costs: float
    contingency: float
    total: float
    per_person: float
    is_estimate: bool = True


def estimate_budget(
    days: int,
    *,
    travelers: int = 1,
    accommodation_per_night: float = 0,
    meals_per_person_day: float = 0,
    local_transport_per_person_day: float = 0,
    activities_per_person: float = 0,
    fixed_costs: float = 0,
    contingency_percent: float = 10,
    currency: str = "USD",
) -> BudgetEstimate:
    """Calculate a transparent trip budget from caller-supplied unit estimates."""
    values = BudgetInput(
        days=days,
        travelers=travelers,
        accommodation_per_night=accommodation_per_night,
        meals_per_person_day=meals_per_person_day,
        local_transport_per_person_day=local_transport_per_person_day,
        activities_per_person=activities_per_person,
        fixed_costs=fixed_costs,
        contingency_percent=contingency_percent,
        currency=currency.upper(),
    )
    accommodation = values.accommodation_per_night * max(values.days - 1, 0)
    meals = values.meals_per_person_day * values.days * values.travelers
    transport = values.local_transport_per_person_day * values.days * values.travelers
    activities = values.activities_per_person * values.travelers
    subtotal = accommodation + meals + transport + activities + values.fixed_costs
    contingency = subtotal * values.contingency_percent / 100
    total = subtotal + contingency
    return BudgetEstimate(
        currency=values.currency,
        accommodation=round(accommodation, 2),
        meals=round(meals, 2),
        local_transport=round(transport, 2),
        activities=round(activities, 2),
        fixed_costs=round(values.fixed_costs, 2),
        contingency=round(contingency, 2),
        total=round(total, 2),
        per_person=round(total / values.travelers, 2),
    )
