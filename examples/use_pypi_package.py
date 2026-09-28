"""Simple AutoResearcher example.

Before running:
    export OPENAI_API_KEY="your-openai-key"

Then run:
    python examples/use_pypi_package.py
"""

from pathlib import Path

from autoresearcher import AutoResearcher
from autoresearcher.errors import AutoResearcherError

# Change these two values for your report.
QUESTION = "Chennai trip for 3 days from 10 December 2026"
OUTPUT_FILE = Path("reports/chennai-trip-report.docx")


researcher = AutoResearcher(
    models={
        "planner": "openai",
        "worker": "openai",
        "critic": "openai",
        "writer": "openai",
    },
    max_subagents=8,
    llm_timeout_seconds=180,
    languages=["tamil", "hindi", "telugu", "malayalam"],
    include_images=True,
    image_limit=5,
)

if researcher.settings.openai_api_key is None:
    raise SystemExit("OPENAI_API_KEY is missing. Export it or add it to a local .env file.")

try:
    result = researcher.run(QUESTION, output=OUTPUT_FILE)
except (AutoResearcherError, ValueError) as exc:
    raise SystemExit(f"Research failed: {exc}") from exc

print(f"Report written: {result.docx_path}")
print(f"Sources used: {len(result.sources)}")
print(f"Token usage: {result.token_usage}")
for warning in result.warnings:
    print(f"Warning: {warning}")
