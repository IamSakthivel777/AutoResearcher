"""Public synchronous, asynchronous, and streaming research APIs."""

from __future__ import annotations

import asyncio
import importlib
import queue
import threading
import warnings as warning_controls
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, cast

from autoresearcher.config import Settings
from autoresearcher.errors import SyncInAsyncError
from autoresearcher.llm.factory import get_llm
from autoresearcher.models import Event
from autoresearcher.report.docx_renderer import DocxRenderer
from autoresearcher.result import RunResult
from autoresearcher.tools.search import web_search

EventSink = Callable[[Event], None]
SearchCallable = Callable[..., Any]

# LangGraph currently emits this dependency warning during a lazy import. Keep the filter
# exact so unrelated deprecations remain visible to applications using this library.
warning_controls.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change.*",
)


class AutoResearcher:
    """Plan research, gather source-backed findings, and write a Word report."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        gemini_api_key: str | None = None,
        search_api_key: str | None = None,
        models: dict[str, str] | None = None,
        max_subagents: int = 8,
        max_critic_loops: int = 2,
        max_tool_calls: int = 6,
        token_budget: int = 100_000,
        task_timeout_seconds: float = 60.0,
        llm_timeout_seconds: float = 180.0,
        languages: list[str] | tuple[str, ...] | None = None,
        include_images: bool = False,
        image_limit: int = 5,
        *,
        _llm: Any | None = None,
        _critic_llm: Any | None = None,
        _writer_llm: Any | None = None,
        _searcher: SearchCallable | None = None,
        _renderer: DocxRenderer | None = None,
    ) -> None:
        values: dict[str, object] = {
            "max_subagents": max_subagents,
            "max_critic_loops": max_critic_loops,
            "max_tool_calls": max_tool_calls,
            "token_budget": token_budget,
            "task_timeout_seconds": task_timeout_seconds,
            "llm_timeout_seconds": llm_timeout_seconds,
        }
        for name, value in (
            ("anthropic_api_key", anthropic_api_key),
            ("openai_api_key", openai_api_key),
            ("gemini_api_key", gemini_api_key),
            ("search_api_key", search_api_key),
            ("models", models),
        ):
            if value is not None:
                values[name] = value
        self.settings = Settings.model_validate(values)
        self._llm = _llm
        self._critic_llm = _critic_llm
        self._writer_llm = _writer_llm
        self._searcher = _searcher or web_search
        self._renderer = _renderer or DocxRenderer()
        normalized_languages = tuple(
            dict.fromkeys(
                language.strip().lower()
                for language in (languages or [])
                if language.strip()
            )
        )
        supported_languages = {"tamil", "hindi", "telugu", "malayalam"}
        invalid_languages = sorted(set(normalized_languages) - supported_languages)
        if invalid_languages:
            raise ValueError(f"Unsupported report languages: {', '.join(invalid_languages)}")
        if not 1 <= image_limit <= 5:
            raise ValueError("image_limit must be between 1 and 5")
        self.languages = normalized_languages
        self.include_images = include_images
        self.image_limit = image_limit

    def __repr__(self) -> str:
        providers = ", ".join(self.settings.configured_providers) or "none"
        return (
            f"AutoResearcher(providers=[{providers}], "
            f"max_subagents={self.settings.max_subagents}, "
            f"max_critic_loops={self.settings.max_critic_loops})"
        )

    def run(self, question: str, output: str | Path = "autoresearcher_report.docx") -> RunResult:
        """Run research synchronously; use ``arun`` inside async applications."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise SyncInAsyncError(
                "AutoResearcher.run() cannot be called from an active event loop; use await arun()."
            )
        return asyncio.run(self.arun(question, output=output))

    async def arun(
        self,
        question: str,
        output: str | Path = "autoresearcher_report.docx",
        *,
        _event_sink: EventSink | None = None,
    ) -> RunResult:
        """Run the parallel LangGraph research flow asynchronously."""
        normalized_question = question.strip()
        if len(normalized_question) < 2:
            raise ValueError("question must contain at least two characters")

        warnings: list[str] = []
        with warning_controls.catch_warnings():
            warning_controls.filterwarnings(
                "ignore",
                message=r"The default value of `allowed_objects` will change.*",
            )
            # Import the module that emits this dependency warning while the narrow
            # filter is active. Later LangGraph imports then reuse the cached module.
            importlib.import_module("langgraph.cache.base")
            from autoresearcher.graph.build import GraphDependencies, build_research_graph
            from autoresearcher.graph.state import ResearchState

        planner_llm = self._llm or get_llm("planner", self.settings, warnings=warnings)
        if self._critic_llm is not None:
            critic_llm = self._critic_llm
        elif self._llm is None:
            critic_llm = get_llm("critic", self.settings, warnings=warnings)
        else:
            # A private planner fake implies an offline test run unless a critic fake is supplied.
            critic_llm = None
        if self.languages or self.include_images:
            if self._writer_llm is not None:
                writer_llm = self._writer_llm
            elif self._llm is None:
                writer_llm = get_llm("writer", self.settings, warnings=warnings)
            else:
                writer_llm = None
        else:
            writer_llm = None

        output_path = str(Path(output).expanduser().resolve())
        graph = build_research_graph(
            GraphDependencies(
                settings=self.settings,
                planner_llm=planner_llm,
                critic_llm=critic_llm,
                output_path=output_path,
                writer_llm=writer_llm,
                languages=self.languages,
                include_images=self.include_images,
                image_limit=self.image_limit,
                searcher=self._searcher,
                renderer=self._renderer,
                event_sink=_event_sink,
                enhance_trip_plan=self._llm is None,
            )
        )
        initial: ResearchState = {
            "question": normalized_question,
            "findings": [],
            "sources": [],
            "warnings": warnings,
            "token_usage": {},
            "loop_count": 0,
            "output_path": output_path,
        }
        final = cast(
            ResearchState,
            await graph.ainvoke(
                initial,
                config={"recursion_limit": 15 + self.settings.max_critic_loops * 5},
            ),
        )
        report_spec = final["report_spec"]
        return RunResult(
            docx_path=Path(final["docx_path"]),
            report_spec=report_spec,
            plan=final["plan"],
            sources=report_spec.sources,
            token_usage=final.get("token_usage", {}),
            warnings=list(dict.fromkeys(final.get("warnings", []))),
        )

    def stream(
        self,
        question: str,
        output: str | Path = "autoresearcher_report.docx",
    ) -> Generator[Event, None, None]:
        """Yield typed progress events while a run executes in a background thread."""
        messages: queue.Queue[Event | BaseException | object] = queue.Queue()
        sentinel = object()

        def target() -> None:
            try:
                asyncio.run(self.arun(question, output=output, _event_sink=messages.put))
            except BaseException as exc:  # propagate the original failure to the consumer
                messages.put(exc)
            finally:
                messages.put(sentinel)

        thread = threading.Thread(target=target, name="autoresearcher-stream", daemon=True)
        thread.start()
        while True:
            message = messages.get()
            if message is sentinel:
                break
            if isinstance(message, BaseException):
                raise message
            yield message  # type: ignore[misc]
        thread.join()

    @staticmethod
    def _emit(sink: EventSink | None, event: Event) -> None:
        if sink is not None:
            sink(event)
