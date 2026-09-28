"""Plain-Python DOCX tool used by the later MCP wrapper."""

from pathlib import Path

from autoresearcher.report.docx_renderer import DocxRenderer
from autoresearcher.report.schema import ReportSpec


def render_docx(report: ReportSpec | dict[str, object], output: str | Path) -> Path:
    """Validate a report specification and render it to a Word document."""
    spec = report if isinstance(report, ReportSpec) else ReportSpec.model_validate(report)
    return DocxRenderer().render(spec, output)
