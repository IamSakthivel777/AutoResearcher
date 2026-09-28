"""Evidence-integrity checks and structured critic evaluation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import ValidationError

from autoresearcher.graph.planner import (
    _invoke_structured,
    prepare_structured_model,
    unwrap_structured,
)
from autoresearcher.models import Critique, Finding, ResearchPlan, Source, Task

CRITIC_PROMPT = """Review the research evidence for gaps and contradictions. Every factual
claim must cite one or more IDs from the supplied source list. Return Critique. Choose 'revise'
only when another bounded research task can materially improve the answer. New tasks must not
contain URLs.

Question: {question}
Plan: {plan}
Findings: {findings}
Sources: {sources}
"""


def _gap_task(task: Task, question: str, index: int) -> Task:
    slug = re.sub(r"[^a-z0-9]+", "-", task.id.lower()).strip("-") or f"task-{index}"
    return Task(
        id=f"gap-{slug}",
        title=f"Fill evidence gap: {task.title}",
        worker_type="web",
        query=f"{question} {task.query}",
        day=task.day,
        priority=5,
    )


def deterministic_critique(
    question: str,
    plan: ResearchPlan,
    findings: list[Finding],
    sources: list[Source],
) -> Critique:
    """Apply non-negotiable citation and coverage checks without an LLM."""
    source_ids = {source.id for source in sources}
    uncited: list[str] = []
    for finding in findings:
        for claim in finding.claims:
            if not claim.source_ids or any(item not in source_ids for item in claim.source_ids):
                uncited.append(claim.text)

    covered = {
        finding.task_id
        for finding in findings
        if finding.claims
        or finding.raw_notes.strip().lower().startswith(("estimate:", "assumption:"))
    }
    def has_gap_coverage(task: Task) -> bool:
        slug = re.sub(r"[^a-z0-9]+", "-", task.id.lower()).strip("-")
        return any(item.startswith(f"gap-{slug}") for item in covered)

    missing_tasks = [
        task for task in plan.tasks if task.id not in covered and not has_gap_coverage(task)
    ]
    gaps = [f"No usable evidence for '{task.title}'." for task in missing_tasks]
    new_tasks = [_gap_task(task, question, index) for index, task in enumerate(missing_tasks, 1)]
    verdict: Literal["pass", "revise"] = "revise" if uncited or gaps else "pass"
    return Critique(
        verdict=verdict,
        gaps=gaps,
        uncited_claims=uncited,
        new_tasks=new_tasks,
    )


async def evaluate_critique(
    question: str,
    plan: ResearchPlan,
    findings: list[Finding],
    sources: list[Source],
    llm: Any | None = None,
    usage_sink: Callable[[int], None] | None = None,
) -> Critique:
    """Run hard checks first, then optionally ask the configured critic model."""
    hard_verdict = deterministic_critique(question, plan, findings, sources)
    if hard_verdict.verdict == "revise" or llm is None:
        return hard_verdict

    structured = prepare_structured_model(llm, Critique)
    prompt = CRITIC_PROMPT.format(
        question=question,
        plan=plan.model_dump_json(),
        findings=json.dumps([item.model_dump(mode="json") for item in findings]),
        sources=json.dumps([item.model_dump(mode="json") for item in sources]),
    )
    error: Exception | None = None
    for attempt in range(2):
        repair = "\nReturn a valid Critique object." if attempt else ""
        try:
            value = await _invoke_structured(structured, prompt + repair)
            parsed, tokens = unwrap_structured(value)
            if usage_sink is not None:
                usage_sink(tokens)
            critique = (
                parsed if isinstance(parsed, Critique) else Critique.model_validate(parsed)
            )
            if critique.verdict == "pass" and (
                critique.gaps or critique.contradictions or critique.uncited_claims
            ):
                critique = critique.model_copy(update={"verdict": "revise"})
            return critique
        except (ValidationError, TypeError, ValueError) as exc:
            error = exc
    error_name = type(error).__name__ if error else "unknown error"
    raise ValueError(f"Critic did not return a valid verdict ({error_name}).") from None
