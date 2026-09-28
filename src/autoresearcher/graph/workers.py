"""Parallel graph worker branches that only derive evidence from tool outputs."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, TypedDict

from autoresearcher.config import Settings
from autoresearcher.errors import ToolError
from autoresearcher.models import Claim, Event, Finding, Source, Task, TaskFinished, TaskStarted
from autoresearcher.tools.memory import retrieve_similar
from autoresearcher.tools.places import search_places
from autoresearcher.tools.search import SearchResponse
from autoresearcher.tools.weather import get_weather_forecast


class WorkerInput(TypedDict):
    """Minimal state sent to each parallel worker through LangGraph ``Send``."""

    task: Task
    question: str
    assumptions: list[str]
    days: int | None
    location: str | None
    start_date: date | None


def _source_id(url: str) -> str:
    number = int(hashlib.sha256(url.rstrip("/").encode()).hexdigest()[:14], 16)
    return f"S{number}"


def _emit(event_sink: Callable[[Event], None] | None, event: Event) -> None:
    if event_sink is not None:
        event_sink(event)


async def _execute_task(
    task: Task,
    *,
    days: int | None,
    location: str | None,
    start_date: date | None,
    settings: Settings,
    searcher: Any,
) -> tuple[Finding, list[Source], list[str]]:
    sources: list[Source] = []
    claims: list[Claim] = []
    warnings: list[str] = []

    if task.worker_type == "places":
        places = await search_places(
            task.query,
            limit=min(settings.max_tool_calls, 10),
            timeout=settings.task_timeout_seconds,
        )
        for place in places:
            source_id = _source_id(str(place.source_url))
            details = f"{place.name}: {place.address}"
            if place.opening_hours:
                details += f". Listed opening hours: {place.opening_hours}"
            sources.append(
                Source(
                    id=source_id,
                    url=place.source_url,
                    title=f"OpenStreetMap: {place.name}",
                    snippet=details,
                    credibility_score=0.75,
                )
            )
            claims.append(Claim(text=details, source_ids=[source_id]))
    elif task.worker_type == "weather":
        forecast_days = days or 7
        latest_forecast_date = date.today() + timedelta(days=15)
        requested_end = (
            start_date + timedelta(days=forecast_days - 1) if start_date else None
        )
        if start_date and (
            start_date < date.today()
            or requested_end is None
            or requested_end > latest_forecast_date
        ):
            warning = (
                f"Exact forecast for {start_date.isoformat()} is outside the available "
                "16-day forecast window; seasonal guidance is used instead."
            )
            return (
                Finding(task_id=task.id, raw_notes=warning),
                [],
                [warning],
            )
        forecast = await get_weather_forecast(
            location or task.query,
            days=forecast_days,
            start_date=start_date,
            timeout=settings.task_timeout_seconds,
        )
        source_id = _source_id(str(forecast.source_url))
        daily_summaries = [
            (
                f"{day.date.isoformat()}: {day.temperature_min_c:g}-"
                f"{day.temperature_max_c:g} °C, "
                f"{day.precipitation_probability_percent}% precipitation probability"
            )
            for day in forecast.days
        ]
        summary = "; ".join(daily_summaries)
        sources.append(
            Source(
                id=source_id,
                url=forecast.source_url,
                title=(
                    f"Open-Meteo forecast for {forecast.location}, starting "
                    f"{forecast.days[0].date.isoformat()}"
                ),
                snippet=summary,
                credibility_score=0.8,
            )
        )
        claims.extend(
            Claim(text=daily_summary, source_ids=[source_id])
            for daily_summary in daily_summaries
        )
    elif task.worker_type == "retrieval":
        uncited_count = 0
        for item in retrieve_similar(task.query, k=min(settings.max_tool_calls, 50)):
            if item.source_url is None:
                uncited_count += 1
                continue
            source_id = _source_id(str(item.source_url))
            sources.append(
                Source(
                    id=source_id,
                    url=item.source_url,
                    title=item.metadata.get("title", "Retrieved document"),
                    snippet=item.text,
                    credibility_score=0.5,
                )
            )
            claims.append(Claim(text=item.text, source_ids=[source_id]))
        if uncited_count:
            warnings.append(
                f"Task '{task.id}' omitted {uncited_count} retrieved item(s) without source URLs."
            )
    else:
        response = await searcher(
            task.query,
            api_key=settings.search_api_key,
            max_results=min(settings.max_tool_calls, 10),
            timeout=settings.task_timeout_seconds,
        )
        response = (
            response
            if isinstance(response, SearchResponse)
            else SearchResponse.model_validate(response)
        )
        if response.warning:
            warnings.append(response.warning)
        for result in response.results:
            url = str(result.url).rstrip("/")
            source_id = _source_id(url)
            claim_text = result.snippet.strip() or result.title.strip()
            sources.append(
                Source(
                    id=source_id,
                    url=result.url,
                    title=result.title,
                    snippet=result.snippet,
                    credibility_score=result.score or 0.5,
                )
            )
            if claim_text:
                claims.append(Claim(text=claim_text, source_ids=[source_id]))

    notes = ""
    if not claims:
        notes = "The tool returned no source-backed claims."
    return Finding(task_id=task.id, claims=claims, raw_notes=notes), sources, warnings


async def run_worker(
    state: WorkerInput,
    *,
    settings: Settings,
    searcher: Any,
    event_sink: Callable[[Event], None] | None = None,
) -> dict[str, object]:
    """Run one bounded tool-using worker without allowing failures to abort siblings."""
    task = state["task"]
    _emit(event_sink, TaskStarted(task=task))
    try:
        finding, sources, warnings = await asyncio.wait_for(
            _execute_task(
                task,
                days=state.get("days"),
                location=state.get("location"),
                start_date=state.get("start_date"),
                settings=settings,
                searcher=searcher,
            ),
            timeout=settings.task_timeout_seconds,
        )
    except Exception as exc:
        finding = Finding(
            task_id=task.id,
            raw_notes="The worker failed before producing source-backed evidence.",
        )
        sources = []
        detail = f" {exc}" if isinstance(exc, ToolError) else ""
        warnings = [
            f"Task '{task.id}' failed ({type(exc).__name__});{detail} continuing."
        ]
    _emit(event_sink, TaskFinished(task_id=task.id, source_count=len(sources)))
    return {"findings": [finding], "sources": sources, "warnings": warnings}
