"""Core data and progress-event models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    """Base model that rejects misspelled fields and hides validation inputs."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Task(StrictModel):
    """One bounded unit of research."""

    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    worker_type: Literal[
        "web", "places", "weather", "budget", "transport", "events", "retrieval"
    ] = "web"
    query: str = Field(min_length=2, max_length=1_000)
    day: int | None = Field(default=None, ge=1)
    priority: int = Field(default=3, ge=1, le=5)


class ResearchPlan(StrictModel):
    """Structured planner output used by the research graph."""

    goal: str = Field(min_length=2)
    assumptions: list[str] = Field(default_factory=list)
    template: Literal["trip", "market_research", "generic"] = "generic"
    todo_list: list[str] = Field(min_length=1)
    tasks: list[Task] = Field(min_length=1)


class Clarification(StrictModel):
    """Deterministically inferred scope used to make planning prompts explicit."""

    days: int | None = Field(default=None, ge=1, le=365)
    location: str | None = Field(default=None, min_length=2, max_length=200)
    start_date: date | None = None
    budget: Literal["budget", "mid-range", "luxury", "unspecified"] = "unspecified"
    interests: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ReportImageQuery(StrictModel):
    """One agent-selected named place and its Commons search query."""

    area_name: str
    query: str


class Source(StrictModel):
    """A source returned by a tool; URLs never originate from the LLM."""

    id: str = Field(pattern=r"^S[1-9][0-9]*$")
    url: HttpUrl
    title: str = Field(min_length=1)
    snippet: str = ""
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    credibility_score: float = Field(default=0.5, ge=0, le=1)


class Claim(StrictModel):
    """A factual statement with one or more supporting source identifiers."""

    text: str = Field(min_length=1)
    source_ids: Annotated[list[str], Field(min_length=1)]


class Finding(StrictModel):
    """Cited output from one research task."""

    task_id: str
    claims: list[Claim] = Field(default_factory=list)
    raw_notes: str = ""


class Critique(StrictModel):
    """Critic decision model used by the later loop and public events."""

    verdict: Literal["pass", "revise"]
    gaps: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    uncited_claims: list[str] = Field(default_factory=list)
    new_tasks: list[Task] = Field(default_factory=list)


class ProgressEvent(StrictModel):
    """Base for typed progress events."""

    type: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanCreated(ProgressEvent):
    type: Literal["plan_created"] = "plan_created"
    plan: ResearchPlan


class TaskStarted(ProgressEvent):
    type: Literal["task_started"] = "task_started"
    task: Task


class TaskFinished(ProgressEvent):
    type: Literal["task_finished"] = "task_finished"
    task_id: str
    source_count: int = Field(ge=0)


class CriticVerdict(ProgressEvent):
    type: Literal["critic_verdict"] = "critic_verdict"
    critique: Critique


class ReportWritten(ProgressEvent):
    type: Literal["report_written"] = "report_written"
    path: str


Event = PlanCreated | TaskStarted | TaskFinished | CriticVerdict | ReportWritten
