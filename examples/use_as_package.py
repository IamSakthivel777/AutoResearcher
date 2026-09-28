"""Minimal example for consuming AutoResearcher as an installed Python package."""

from __future__ import annotations

import argparse
from pathlib import Path

from autoresearcher import AutoResearcher
from autoresearcher.errors import AutoResearcherError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Research question")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("research-report.docx"),
        help="Destination DOCX file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    researcher = AutoResearcher(
        models={
            "planner": "openai",
            "critic": "openai",
            "writer": "openai",
        },
        max_subagents=8,
        max_critic_loops=1,
        llm_timeout_seconds=180,
        languages=["tamil", "hindi", "telugu", "malayalam"],
        include_images=True,
        image_limit=5,
    )
    try:
        result = researcher.run(args.question, output=args.output)
    except (AutoResearcherError, ValueError) as exc:
        print(f"Research failed: {exc}")
        return 1

    print(f"Report: {result.docx_path}")
    print(f"Sources: {len(result.sources)}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
