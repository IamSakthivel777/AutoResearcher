"""AutoResearcher public API."""

from autoresearcher.core import AutoResearcher
from autoresearcher.models import (
    CriticVerdict,
    PlanCreated,
    ReportWritten,
    TaskFinished,
    TaskStarted,
)
from autoresearcher.result import RunResult

__all__ = [
    "AutoResearcher",
    "CriticVerdict",
    "PlanCreated",
    "ReportWritten",
    "RunResult",
    "TaskFinished",
    "TaskStarted",
]
__version__ = "0.1.1"
