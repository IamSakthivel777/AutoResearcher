"""Public run result."""

from pathlib import Path

from pydantic import Field

from autoresearcher.models import ResearchPlan, Source, StrictModel
from autoresearcher.report.schema import ReportSpec


class RunResult(StrictModel):
    """Artifacts, provenance, usage, and warnings from a completed run."""

    docx_path: Path
    report_spec: ReportSpec
    plan: ResearchPlan
    sources: list[Source]
    token_usage: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

