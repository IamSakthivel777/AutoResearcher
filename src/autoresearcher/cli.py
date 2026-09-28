"""Command-line entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from autoresearcher import AutoResearcher
from autoresearcher.errors import AutoResearcherError

console = Console()


def command(
    question: Annotated[str, typer.Argument(help="Research question")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Destination .docx file"),
    ] = Path("autoresearcher_report.docx"),
    models: Annotated[
        str | None,
        typer.Option(help="Comma-separated role=provider routes"),
    ] = None,
    max_subagents: Annotated[int, typer.Option(min=1, max=64)] = 8,
    llm_timeout: Annotated[
        float,
        typer.Option(min=1, max=600, help="Seconds allowed for each LLM request"),
    ] = 180,
    languages: Annotated[
        str,
        typer.Option(
            help="Comma-separated translated highlights: tamil,hindi,telugu,malayalam"
        ),
    ] = "",
    images: Annotated[
        bool,
        typer.Option("--images/--no-images", help="Add licensed Wikimedia Commons images"),
    ] = False,
) -> None:
    """Research QUESTION and write a cited Word report."""
    routes: dict[str, str] = {}
    if models:
        try:
            routes = dict(item.split("=", 1) for item in models.split(","))
        except ValueError:
            console.print("[red]--models must look like planner=claude,worker=gemini[/red]")
            raise typer.Exit(2) from None
    try:
        selected_languages = [
            language.strip() for language in languages.split(",") if language.strip()
        ]
        with console.status("Researching…"):
            result = AutoResearcher(
                models=routes,
                max_subagents=max_subagents,
                llm_timeout_seconds=llm_timeout,
                languages=selected_languages,
                include_images=images,
            ).run(question, output=output)
    except (AutoResearcherError, ValueError) as exc:
        console.print(f"[red]Research failed:[/red] {exc}")
        raise typer.Exit(1) from None
    console.print(f"[green]Report written:[/green] {result.docx_path}")
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


def main() -> None:
    """Run the Typer application."""
    typer.run(command)


if __name__ == "__main__":  # pragma: no cover
    main()
