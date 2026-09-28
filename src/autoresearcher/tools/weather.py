"""No-key weather forecasts from Open-Meteo."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from autoresearcher.errors import ToolError


class WeatherInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    location: str = Field(min_length=2, max_length=300)
    days: int = Field(default=7, ge=1, le=16)
    start_date: date | None = None
    timeout: float = Field(default=15.0, gt=0, le=60)


class DailyWeather(BaseModel):
    date: date
    temperature_min_c: float
    temperature_max_c: float
    precipitation_probability_percent: int = Field(ge=0, le=100)
    weather_code: int


class WeatherForecast(BaseModel):
    location: str
    latitude: float
    longitude: float
    timezone: str
    days: list[DailyWeather]
    source_url: HttpUrl


async def get_weather_forecast(
    location: str,
    *,
    days: int = 7,
    start_date: date | None = None,
    timeout: float = 15.0,
) -> WeatherForecast:
    """Geocode a location and retrieve its daily Open-Meteo forecast."""
    inputs = WeatherInput(
        location=location,
        days=days,
        start_date=start_date,
        timeout=timeout,
    )
    try:
        async with httpx.AsyncClient(timeout=inputs.timeout) as client:
            geocode_response = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": inputs.location, "count": 1, "language": "en"},
            )
            geocode_response.raise_for_status()
            geocodes = geocode_response.json().get("results") or []
            if not geocodes:
                raise ToolError(f"No coordinates found for '{inputs.location}'")
            place = geocodes[0]
            forecast_params: dict[str, str | int | float] = {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max"
                ),
                "timezone": "auto",
            }
            if inputs.start_date is None:
                forecast_params["forecast_days"] = inputs.days
            else:
                forecast_params["start_date"] = inputs.start_date.isoformat()
                forecast_params["end_date"] = (
                    inputs.start_date + timedelta(days=inputs.days - 1)
                ).isoformat()
            forecast_response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params=forecast_params,
            )
            forecast_response.raise_for_status()
            payload = forecast_response.json()
    except ToolError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ToolError(f"Weather forecast failed ({type(exc).__name__}).") from None

    daily = payload.get("daily") or {}
    try:
        rows = [
            DailyWeather(
                date=day,
                temperature_min_c=daily["temperature_2m_min"][index],
                temperature_max_c=daily["temperature_2m_max"][index],
                precipitation_probability_percent=(
                    daily["precipitation_probability_max"][index] or 0
                ),
                weather_code=daily["weather_code"][index],
            )
            for index, day in enumerate(daily["time"])
        ]
    except (KeyError, IndexError, TypeError) as exc:
        raise ToolError(f"Weather response was incomplete ({type(exc).__name__}).") from None
    return WeatherForecast.model_validate(
        {
            "location": place.get("name") or inputs.location,
            "latitude": payload["latitude"],
            "longitude": payload["longitude"],
            "timezone": payload.get("timezone") or "UTC",
            "days": rows,
            "source_url": str(forecast_response.request.url),
        }
    )
