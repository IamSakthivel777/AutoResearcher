"""Structured research planning node."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from autoresearcher.errors import PlanningError
from autoresearcher.models import Clarification, Critique, ResearchPlan, Task

PLANNER_PROMPT = """You are a research planner. Decompose the user's question into a small,
focused plan. Return the required ResearchPlan schema. Choose the most relevant worker_type
for each task. Search queries should be specific and should collectively cover the question.
Do not include URLs or factual answers; only plan the research.

User question: {question}
Clarified assumptions: {assumptions}
"""


def _is_transient_llm_error(exc: BaseException) -> bool:
    """Recognize timeout and rate-limit errors without importing provider SDK internals."""
    return isinstance(exc, TimeoutError) or type(exc).__name__ in {
        "APITimeoutError",
        "DeadlineExceeded",
        "RateLimitError",
        "ResourceExhausted",
    }


@retry(
    retry=retry_if_exception(_is_transient_llm_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def _invoke_structured(structured: Any, prompt: str) -> Any:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Pydantic serializer warnings:",
            category=UserWarning,
            module=r"pydantic\.main",
        )
        return await structured.ainvoke(prompt)


def prepare_structured_model(llm: Any, schema: type[Any]) -> Any:
    """Request raw usage metadata when supported, retaining simple fake compatibility."""
    kwargs: dict[str, object] = {"include_raw": True}
    if type(llm).__module__.startswith("langchain_openai"):
        # Our rich Pydantic models intentionally use validation keywords outside
        # OpenAI's strict JSON Schema subset. Function calling supports them as a
        # non-strict tool schema and Pydantic still validates the parsed result.
        kwargs["method"] = "function_calling"
    try:
        return llm.with_structured_output(schema, **kwargs)
    except TypeError:
        return llm.with_structured_output(schema)


def unwrap_structured(value: Any) -> tuple[Any, int]:
    """Return parsed structured output and its reported token count, if available."""
    raw = None
    parsed = value
    if isinstance(value, dict) and "parsed" in value and "raw" in value:
        parsed = value.get("parsed")
        raw = value.get("raw")
    usage = getattr(raw, "usage_metadata", None) or {}
    response_metadata = getattr(raw, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or {}
    total = usage.get("total_tokens") or token_usage.get("total_tokens") or 0
    return parsed, int(total)


async def create_plan(
    question: str,
    llm: Any,
    assumptions: list[str] | None = None,
    usage_sink: Callable[[int], None] | None = None,
) -> ResearchPlan:
    """Invoke a model with structured output and one validation-repair retry."""
    structured = prepare_structured_model(llm, ResearchPlan)
    prompt = PLANNER_PROMPT.format(
        question=question,
        assumptions="; ".join(assumptions or []) or "None",
    )
    error: Exception | None = None
    for attempt in range(2):
        repair = (
            "\nYour previous output was invalid. Return only a valid ResearchPlan."
            if attempt
            else ""
        )
        try:
            value = await _invoke_structured(structured, prompt + repair)
            parsed, tokens = unwrap_structured(value)
            if usage_sink is not None:
                usage_sink(tokens)
            return (
                parsed
                if isinstance(parsed, ResearchPlan)
                else ResearchPlan.model_validate(parsed)
            )
        except (ValidationError, TypeError, ValueError) as exc:
            error = exc
        except Exception as exc:
            if _is_transient_llm_error(exc):
                raise PlanningError(
                    "Planner request timed out after retries. Retry the run or increase "
                    "llm_timeout_seconds."
                ) from None
            raise PlanningError(f"Planner request failed ({type(exc).__name__}).") from None
    error_name = type(error).__name__ if error else "unknown error"
    raise PlanningError(f"Planner did not return a valid ResearchPlan ({error_name}).") from None


def add_critique_tasks(
    plan: ResearchPlan,
    critique: Critique,
    *,
    loop_count: int,
) -> tuple[ResearchPlan, list[Task]]:
    """Merge critic-proposed work into the plan, making colliding task IDs unique."""
    existing_ids = {task.id for task in plan.tasks}
    pending: list[Task] = []
    for index, task in enumerate(critique.new_tasks, 1):
        task_id = task.id
        if task_id in existing_ids:
            suffix = f"-r{loop_count}-{index}"
            task_id = f"{task_id[: 80 - len(suffix)]}{suffix}"
        revised = Task.model_validate({**task.model_dump(), "id": task_id})
        existing_ids.add(task_id)
        pending.append(revised)
    todo = [*plan.todo_list, *(f"Resolve gap: {gap}" for gap in critique.gaps)]
    revised_plan = plan.model_copy(
        update={
            "todo_list": list(dict.fromkeys(todo)),
            "tasks": [*plan.tasks, *pending],
        }
    )
    return revised_plan, pending


def ensure_trip_essentials(
    plan: ResearchPlan,
    clarification: Clarification | None,
) -> ResearchPlan:
    """Guarantee separate forecast and seasonal-guidance tasks for trip reports."""
    if plan.template != "trip" or clarification is None or not clarification.location:
        return plan

    location = clarification.location
    weather_task = next(
        (task for task in plan.tasks if task.worker_type == "weather"),
        None,
    )
    if weather_task is None:
        weather_task = Task(
            id="weather-forecast",
            title=f"Current weather forecast for {location}",
            worker_type="weather",
            query=location,
            priority=5,
        )
    else:
        weather_task = Task.model_validate(
            {**weather_task.model_dump(), "query": location, "priority": 5}
        )

    seasonal_task = next(
        (
            task
            for task in plan.tasks
            if task.worker_type != "weather"
            and any(
                phrase in f"{task.title} {task.query}".lower()
                for phrase in ("best time", "seasonal", "climate")
            )
        ),
        None,
    )
    if seasonal_task is None:
        seasonal_task = Task(
            id="best-time-to-visit",
            title=f"Best time to visit {location}",
            worker_type="web",
            query=f"{location} best time to visit seasonal climate official tourism",
            priority=5,
        )

    essential_ids = {weather_task.id, seasonal_task.id}
    remaining = [task for task in plan.tasks if task.id not in essential_ids]
    todo = [
        "Add a sourced current forecast and seasonal best-time guidance.",
        *plan.todo_list,
    ]
    return plan.model_copy(
        update={
            "todo_list": list(dict.fromkeys(todo)),
            "tasks": [weather_task, seasonal_task, *remaining],
        }
    )
