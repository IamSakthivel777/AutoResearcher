"""LangGraph assembly and report construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from autoresearcher.config import Settings
from autoresearcher.graph.clarifier import clarify_question
from autoresearcher.graph.critic import evaluate_critique
from autoresearcher.graph.planner import (
    add_critique_tasks,
    create_plan,
    ensure_trip_essentials,
)
from autoresearcher.graph.state import ResearchState
from autoresearcher.models import (
    CriticVerdict,
    Event,
    Finding,
    PlanCreated,
    ReportWritten,
    ResearchPlan,
    Source,
)
from autoresearcher.report.docx_renderer import DocxRenderer
from autoresearcher.report.schema import (
    BulletsBlock,
    CalloutBlock,
    HeadingBlock,
    ParagraphBlock,
    ReportBlock,
    ReportSpec,
    Section,
)
from autoresearcher.tools.search import web_search


@dataclass
class GraphDependencies:
    """Per-run dependencies captured by graph node closures."""

    settings: Settings
    planner_llm: Any
    critic_llm: Any | None
    output_path: str
    writer_llm: Any | None = None
    languages: tuple[str, ...] = ()
    include_images: bool = False
    image_limit: int = 5
    searcher: Any = web_search
    renderer: DocxRenderer | None = None
    event_sink: Any | None = None
    enhance_trip_plan: bool = True

    def emit(self, event: Event) -> None:
        if self.event_sink is not None:
            self.event_sink(event)


def build_report_spec(
    question: str,
    plan: ResearchPlan,
    findings: list[Finding],
    sources: list[Source],
) -> ReportSpec:
    """Build a conservative report from tool-produced, cited search snippets."""
    clarification = clarify_question(question)
    sections = [
        Section(
            title="Trip at a glance" if plan.template == "trip" else "Research overview",
            blocks=[
                CalloutBlock(
                    kind="tip",
                    text="Use this report as a planning guide and recheck time-sensitive details.",
                    factual=False,
                ),
                ParagraphBlock(text=f"Research question: {question}", factual=False),
                BulletsBlock(items=plan.todo_list, factual=False),
            ],
        )
    ]
    tasks = {task.id: task for task in plan.tasks}

    def blocks_for(finding: Finding) -> list[ReportBlock]:
        task = tasks.get(finding.task_id)
        if task and task.worker_type == "weather" and finding.claims:
            source_ids = list(
                dict.fromkeys(
                    source_id
                    for claim in finding.claims
                    for source_id in claim.source_ids
                )
            )
            blocks: list[ReportBlock] = [
                CalloutBlock(
                    kind="info",
                    text=(
                        f"This forecast starts on the user-provided travel date, "
                        f"{clarification.start_date.isoformat()}; verify it again shortly "
                        "before travel."
                        if clarification.start_date
                        else (
                            f"No travel date was provided. This live forecast starts on the "
                            f"report date, {date.today().isoformat()}, and does not assign "
                            "dates to the itinerary."
                        )
                    ),
                    factual=False,
                ),
                BulletsBlock(
                    items=[claim.text for claim in finding.claims],
                    source_ids=source_ids,
                ),
            ]
        else:
            blocks = [
                ParagraphBlock(text=claim.text, source_ids=claim.source_ids)
                for claim in finding.claims
            ]
        if not blocks:
            blocks.append(
                ParagraphBlock(
                    text="No usable source-backed findings were returned for this task.",
                    factual=False,
                )
            )
        if finding.raw_notes.strip():
            blocks.append(
                ParagraphBlock(
                    text=f"Note (not a sourced factual claim): {finding.raw_notes.strip()}",
                    factual=False,
                )
            )
        return blocks

    consumed: set[str] = set()
    if plan.template == "trip":
        weather_findings = []
        for finding in findings:
            task = tasks.get(finding.task_id)
            label = f"{task.title} {task.query}".lower() if task else ""
            if task and (
                task.worker_type == "weather"
                or any(phrase in label for phrase in ("best time", "seasonal", "climate"))
            ):
                weather_findings.append(finding)
        if weather_findings:
            weather_blocks: list[ReportBlock] = []
            for finding in weather_findings:
                task = tasks.get(finding.task_id)
                if task:
                    weather_blocks.append(HeadingBlock(text=task.title, level=2))
                weather_blocks.extend(blocks_for(finding))
                consumed.add(finding.task_id)
            sections.append(
                Section(title="Weather & best time to visit", blocks=weather_blocks)
            )

    for finding in findings:
        if finding.task_id in consumed:
            continue
        task = tasks.get(finding.task_id)
        title = task.title if task else finding.task_id
        sections.append(Section(title=title, blocks=blocks_for(finding)))

    return ReportSpec(
        title=plan.goal,
        subtitle="Source-grounded research report",
        assumptions=plan.assumptions,
        metadata={
            "question": question,
            "template": plan.template,
            "travel_start_date": (
                clarification.start_date.isoformat()
                if clarification.start_date
                else "not provided"
            ),
        },
        sections=sections,
        sources=sources,
    )


def build_research_graph(dependencies: GraphDependencies) -> Any:
    """Compile the Phase 2 graph with parallel worker fan-out and critic loops."""
    from autoresearcher.graph.synthesizer import (
        add_multilingual_guides,
        add_report_images,
        default_image_queries,
        plan_report_images,
        synthesize_report,
    )
    from autoresearcher.graph.workers import WorkerInput, run_worker

    settings = dependencies.settings

    async def clarifier_node(state: ResearchState) -> dict[str, object]:
        clarification = clarify_question(state["question"])
        return {
            "clarification": clarification,
            "assumptions": clarification.assumptions,
        }

    async def planner_node(state: ResearchState) -> dict[str, object]:
        warnings: list[str] = []
        planner_tokens = 0

        def add_planner_tokens(tokens: int) -> None:
            nonlocal planner_tokens
            planner_tokens += tokens

        if "plan" not in state:
            plan = await create_plan(
                state["question"],
                dependencies.planner_llm,
                state.get("assumptions", []),
                add_planner_tokens,
            )
            plan = plan.model_copy(
                update={
                    "assumptions": list(
                        dict.fromkeys([*state.get("assumptions", []), *plan.assumptions])
                    )
                }
            )
            if dependencies.enhance_trip_plan:
                plan = ensure_trip_essentials(plan, state.get("clarification"))
            pending = sorted(plan.tasks, key=lambda task: task.priority, reverse=True)
        else:
            plan, added = add_critique_tasks(
                state["plan"],
                state["critique"],
                loop_count=state.get("loop_count", 1),
            )
            pending = sorted(added, key=lambda task: task.priority, reverse=True)

        completed_ids = {finding.task_id for finding in state.get("findings", [])}
        remaining = max(settings.max_subagents - len(completed_ids), 0)
        if len(pending) > remaining:
            warnings.append(
                f"Planned work was limited to max_subagents={settings.max_subagents}."
            )
            allowed_ids = {task.id for task in pending[:remaining]}
            pending = pending[:remaining]
            plan = plan.model_copy(
                update={
                    "tasks": [
                        task
                        for task in plan.tasks
                        if task.id in completed_ids or task.id in allowed_ids
                    ]
                }
            )
        dependencies.emit(PlanCreated(plan=plan))
        return {
            "plan": plan,
            "pending_tasks": pending,
            "warnings": warnings,
            "token_usage": {"planner": planner_tokens} if planner_tokens else {},
        }

    async def dispatch_workers(state: ResearchState) -> list[Send] | str:
        pending = state.get("pending_tasks", [])
        if not pending:
            return "critic"
        clarification = state.get("clarification")
        return [
            Send(
                "worker",
                WorkerInput(
                    task=task,
                    question=state["question"],
                    assumptions=state.get("assumptions", []),
                    days=clarification.days if clarification else None,
                    location=clarification.location if clarification else None,
                    start_date=clarification.start_date if clarification else None,
                ),
            )
            for task in pending
        ]

    async def worker_node(state: WorkerInput) -> dict[str, object]:
        return await run_worker(
            state,
            settings=settings,
            searcher=dependencies.searcher,
            event_sink=dependencies.event_sink,
        )

    async def critic_node(state: ResearchState) -> dict[str, object]:
        warnings: list[str] = []
        critic_tokens = 0

        def add_critic_tokens(tokens: int) -> None:
            nonlocal critic_tokens
            critic_tokens += tokens

        used_tokens = sum(state.get("token_usage", {}).values())
        critic_llm = dependencies.critic_llm
        if used_tokens >= settings.token_budget:
            critic_llm = None
            warnings.append("Token budget reached; used deterministic critic checks.")
        try:
            critique = await evaluate_critique(
                state["question"],
                state["plan"],
                state.get("findings", []),
                state.get("sources", []),
                critic_llm,
                add_critic_tokens,
            )
        except Exception as exc:
            critique = await evaluate_critique(
                state["question"],
                state["plan"],
                state.get("findings", []),
                state.get("sources", []),
            )
            warnings.append(f"LLM critic failed ({type(exc).__name__}); used hard checks.")

        loop_count = state.get("loop_count", 0)
        if critique.verdict == "revise":
            loop_count += 1
            completed = {finding.task_id for finding in state.get("findings", [])}
            if loop_count > settings.max_critic_loops:
                warnings.append("Critic loop limit reached; synthesizing available evidence.")
            elif len(completed) >= settings.max_subagents:
                warnings.append("Sub-agent limit reached; synthesizing available evidence.")
        dependencies.emit(CriticVerdict(critique=critique))
        return {
            "critique": critique,
            "loop_count": loop_count,
            "warnings": warnings,
            "token_usage": {"critic": critic_tokens} if critic_tokens else {},
        }

    async def after_critic(state: ResearchState) -> str:
        if state["critique"].verdict == "pass":
            return "synthesizer"
        if state.get("loop_count", 0) > settings.max_critic_loops:
            return "synthesizer"
        completed = {finding.task_id for finding in state.get("findings", [])}
        if len(completed) >= settings.max_subagents:
            return "synthesizer"
        return "planner"

    async def synthesizer_node(state: ResearchState) -> dict[str, object]:
        report = synthesize_report(
            state["question"],
            state["plan"],
            state.get("findings", []),
            state.get("sources", []),
        )
        warnings: list[str] = []
        writer_tokens = 0

        def add_writer_tokens(tokens: int) -> None:
            nonlocal writer_tokens
            writer_tokens += tokens

        if dependencies.languages:
            used_tokens = sum(state.get("token_usage", {}).values())
            if dependencies.writer_llm is None:
                warnings.append("Translations were requested but no writer model is available.")
            elif used_tokens >= settings.token_budget:
                warnings.append("Token budget reached; multilingual highlights were skipped.")
            else:
                try:
                    report = await add_multilingual_guides(
                        report,
                        dependencies.languages,
                        dependencies.writer_llm,
                        add_writer_tokens,
                    )
                except Exception as exc:
                    warnings.append(
                        f"Multilingual highlights failed ({type(exc).__name__}); continuing."
                    )
        image_queries = []
        if dependencies.include_images:
            clarification = state.get("clarification")
            location = (
                clarification.location
                if clarification and clarification.location
                else report.title
            )
            used_tokens = sum(state.get("token_usage", {}).values()) + writer_tokens
            if dependencies.writer_llm is None:
                warnings.append(
                    "Image-planning model is unavailable; using category-based image searches."
                )
                image_queries = default_image_queries(location, dependencies.image_limit)
            elif used_tokens >= settings.token_budget:
                warnings.append("Token budget reached; using category-based image searches.")
                image_queries = default_image_queries(location, dependencies.image_limit)
            else:
                try:
                    image_queries = await plan_report_images(
                        report,
                        location=location,
                        limit=dependencies.image_limit,
                        llm=dependencies.writer_llm,
                        usage_sink=add_writer_tokens,
                    )
                except Exception as exc:
                    warnings.append(
                        f"Image planning failed ({type(exc).__name__}); using fallback searches."
                    )
                    image_queries = default_image_queries(
                        location, dependencies.image_limit
                    )
        return {
            "report_spec": report,
            "image_queries": image_queries,
            "warnings": warnings,
            "token_usage": {"writer": writer_tokens} if writer_tokens else {},
        }

    async def renderer_node(state: ResearchState) -> dict[str, object]:
        renderer = dependencies.renderer or DocxRenderer()
        report = state["report_spec"]
        warnings: list[str] = []
        if dependencies.include_images:
            clarification = state.get("clarification")
            location = (
                clarification.location
                if clarification and clarification.location
                else report.title
            )
            queries = state.get("image_queries") or default_image_queries(
                location, dependencies.image_limit
            )
            output = Path(dependencies.output_path)
            asset_directory = output.parent / f".{output.stem}_assets"
            report, image_warnings = await add_report_images(
                report,
                queries=queries,
                asset_directory=asset_directory,
                limit=dependencies.image_limit,
            )
            warnings.extend(image_warnings)
        path = renderer.render(report, dependencies.output_path)
        dependencies.emit(ReportWritten(path=str(path)))
        return {
            "docx_path": str(path),
            "report_spec": report,
            "warnings": warnings,
        }

    graph = StateGraph(ResearchState)
    graph.add_node("clarifier", clarifier_node)
    graph.add_node("planner", planner_node)
    graph.add_node("worker", worker_node)
    graph.add_node("critic", critic_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("renderer", renderer_node)
    graph.add_edge(START, "clarifier")
    graph.add_edge("clarifier", "planner")
    graph.add_conditional_edges("planner", dispatch_workers, ["worker", "critic"])
    graph.add_edge("worker", "critic")
    graph.add_conditional_edges(
        "critic",
        after_critic,
        {"planner": "planner", "synthesizer": "synthesizer"},
    )
    graph.add_edge("synthesizer", "renderer")
    graph.add_edge("renderer", END)
    return cast(Any, graph.compile())
