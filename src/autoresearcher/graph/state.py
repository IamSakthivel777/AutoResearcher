"""State types and reducers shared by graph phases."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from autoresearcher.models import (
    Clarification,
    Critique,
    Finding,
    ReportImageQuery,
    ResearchPlan,
    Source,
    Task,
)
from autoresearcher.report.schema import ReportSpec


def dedupe_sources(left: list[Source], right: list[Source]) -> list[Source]:
    """Append only sources whose normalized URLs have not already appeared."""
    result = list(left)
    seen = {str(source.url).rstrip("/") for source in left}
    for source in right:
        normalized = str(source.url).rstrip("/")
        if normalized not in seen:
            result.append(source)
            seen.add(normalized)
    return result


def merge_token_usage(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    """Sum token counters emitted concurrently by graph nodes."""
    merged = dict(left)
    for role, tokens in right.items():
        merged[role] = merged.get(role, 0) + tokens
    return merged


class ResearchState(TypedDict, total=False):
    """Forward-compatible state for the LangGraph implementation."""

    question: str
    assumptions: list[str]
    clarification: Clarification
    plan: ResearchPlan
    pending_tasks: list[Task]
    findings: Annotated[list[Finding], operator.add]
    sources: Annotated[list[Source], dedupe_sources]
    critique: Critique
    loop_count: int
    report_spec: ReportSpec
    image_queries: list[ReportImageQuery]
    docx_path: str
    warnings: Annotated[list[str], operator.add]
    token_usage: Annotated[dict[str, int], merge_token_usage]
    output_path: str
