"""Run a real AutoResearcher report using a user-provided OpenAI API key.

Usage:
    export OPENAI_API_KEY="..."
    python examples/test_openai_live.py "Chennai trip for 3 days" -o chennai.docx

The key may instead be stored as OPENAI_API_KEY in the project's local .env file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from autoresearcher import AutoResearcher
from autoresearcher.errors import AutoResearcherError


def parse_args() -> argparse.Namespace:
    """Parse the research question and output location."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "question",
        nargs="?",
        default="Chennai trip for 3 days",
        help="Question to research",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("openai_research_report.docx"),
        help="Destination DOCX file",
    )
    parser.add_argument(
        "--max-subagents",
        type=int,
        default=8,
        help="Maximum workers for this paid live test",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=180,
        help="Seconds allowed for each OpenAI model request",
    )
    parser.add_argument(
        "--languages",
        default="tamil,hindi,telugu,malayalam",
        help="Comma-separated translated highlight languages; use an empty value to disable",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Disable licensed Wikimedia Commons images",
    )
    return parser.parse_args()


def main() -> int:
    """Run the live report and print only non-secret result metadata."""
    args = parse_args()
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    researcher = AutoResearcher(
        models={
            "planner": "openai",
            "worker": "openai",
            "critic": "openai",
            "writer": "openai",
        },
        max_subagents=args.max_subagents,
        max_critic_loops=1,
        llm_timeout_seconds=args.llm_timeout,
        languages=languages,
        include_images=not args.no_images,
        image_limit=5,
    )

    if researcher.settings.openai_api_key is None:
        print("OPENAI_API_KEY is missing. Set it in the environment or local .env file.")
        return 2

    print(f"Researching: {args.question}")
    try:
        result = researcher.run(args.question, output=args.output)
    except (AutoResearcherError, ValueError) as exc:
        print(f"Research failed: {exc}")
        return 1

    print(f"Report: {result.docx_path}")
    print(f"Sources: {len(result.sources)}")
    print(f"Token usage: {result.token_usage}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
