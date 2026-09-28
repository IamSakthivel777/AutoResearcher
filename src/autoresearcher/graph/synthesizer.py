"""Source-safe deterministic synthesis for Phase 2."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docx.image.exceptions import UnrecognizedImageError
from docx.image.image import Image as DocxImage
from pydantic import ValidationError

from autoresearcher.graph.build import build_report_spec
from autoresearcher.graph.planner import (
    _invoke_structured,
    prepare_structured_model,
    unwrap_structured,
)
from autoresearcher.models import (
    Claim,
    Finding,
    ReportImageQuery,
    ResearchPlan,
    Source,
    StrictModel,
)
from autoresearcher.report.schema import (
    BulletsBlock,
    CalloutBlock,
    ImageBlock,
    ImageGalleryBlock,
    ParagraphBlock,
    ReportSpec,
    Section,
)
from autoresearcher.tools.images import download_image, search_images

LANGUAGE_LABELS = {
    "tamil": ("Tamil", "தமிழ்", "விரைவு வழிகாட்டி"),
    "hindi": ("Hindi", "हिन्दी", "त्वरित मार्गदर्शिका"),
    "telugu": ("Telugu", "తెలుగు", "త్వరిత మార్గదర్శిని"),
    "malayalam": ("Malayalam", "മലയാളം", "ദ്രുത ഗൈഡ്"),
}


class TranslationEntry(StrictModel):
    index: int
    tamil: str
    hindi: str
    telugu: str
    malayalam: str


class TranslationPack(StrictModel):
    entries: list[TranslationEntry]


class ImageQueryPlan(StrictModel):
    items: list[ReportImageQuery]


def _ensure_docx_compatible_image(path: Path) -> bool:
    """Validate an image and add a standard JFIF marker when Commons omits it."""
    try:
        DocxImage.from_file(str(path))
    except (UnrecognizedImageError, OSError, ValueError):
        try:
            content = path.read_bytes()
            if not content.startswith(b"\xff\xd8"):
                return False
            jfif_segment = bytes.fromhex("FFE000104A46494600010100000100010000")
            path.write_bytes(content[:2] + jfif_segment + content[2:])
            DocxImage.from_file(str(path))
        except (UnrecognizedImageError, OSError, ValueError):
            return False
    return True


def synthesize_report(
    question: str,
    plan: ResearchPlan,
    findings: list[Finding],
    sources: list[Source],
) -> ReportSpec:
    """Deduplicate and renumber evidence before building the final report spec."""
    unique_sources: list[Source] = []
    new_id_by_old_id: dict[str, str] = {}
    new_id_by_url: dict[str, str] = {}
    for source in sources:
        url = str(source.url).rstrip("/")
        new_id = new_id_by_url.get(url)
        if new_id is None:
            new_id = f"S{len(unique_sources) + 1}"
            new_id_by_url[url] = new_id
            unique_sources.append(source.model_copy(update={"id": new_id}))
        new_id_by_old_id[source.id] = new_id

    normalized_findings: list[Finding] = []
    for finding in findings:
        claims: list[Claim] = []
        for claim in finding.claims:
            mapped = list(
                dict.fromkeys(
                    new_id_by_old_id[source_id]
                    for source_id in claim.source_ids
                    if source_id in new_id_by_old_id
                )
            )
            if mapped:
                claims.append(claim.model_copy(update={"source_ids": mapped}))
        normalized_findings.append(finding.model_copy(update={"claims": claims}))

    return build_report_spec(question, plan, normalized_findings, unique_sources)


def _translation_inputs(report: ReportSpec, limit: int = 10) -> list[tuple[str, list[str]]]:
    items: list[tuple[str, list[str]]] = []
    for section in report.sections:
        for block in section.blocks:
            if isinstance(block, ParagraphBlock) and block.factual:
                items.append((block.text, block.source_ids))
            elif isinstance(block, BulletsBlock) and block.factual:
                items.extend((text, block.source_ids) for text in block.items)
            if len(items) >= limit:
                return items[:limit]
    return items


async def add_multilingual_guides(
    report: ReportSpec,
    languages: tuple[str, ...],
    llm: Any,
    usage_sink: Callable[[int], None] | None = None,
) -> ReportSpec:
    """Add faithful translated highlights while preserving original citation IDs."""
    items = _translation_inputs(report)
    if not items or not languages:
        return report
    prompt = (
        "Translate each numbered travel-research statement faithfully into Tamil, Hindi, "
        "Telugu, and Malayalam. Do not add, omit, soften, or update facts. Return one entry "
        "per index and populate all four required language fields.\n"
        f"Statements: {json.dumps([text for text, _source_ids in items])}"
    )
    structured = prepare_structured_model(llm, TranslationPack)
    error: Exception | None = None
    for attempt in range(2):
        repair = "\nReturn all requested translations with matching indices." if attempt else ""
        try:
            raw = await _invoke_structured(structured, prompt + repair)
            parsed, tokens = unwrap_structured(raw)
            if usage_sink is not None:
                usage_sink(tokens)
            pack = (
                parsed
                if isinstance(parsed, TranslationPack)
                else TranslationPack.model_validate(parsed)
            )
            by_index = {entry.index: entry for entry in pack.entries}
            sections: list[Section] = []
            for language in languages:
                paragraphs = []
                for index, (_text, source_ids) in enumerate(items):
                    entry = by_index.get(index)
                    translated = getattr(entry, language, "").strip() if entry else ""
                    if translated:
                        paragraphs.append(
                            ParagraphBlock(text=translated, source_ids=source_ids)
                        )
                if paragraphs:
                    english, native, heading = LANGUAGE_LABELS[language]
                    sections.append(
                        Section(
                            title=f"{heading} — {native} ({english})",
                            blocks=[
                                CalloutBlock(
                                    kind="info",
                                    text=(
                                        "Machine-translated highlights; verify critical wording "
                                        "against the cited source."
                                    ),
                                    factual=False,
                                ),
                                *paragraphs,
                            ],
                        )
                    )
            return report.model_copy(update={"sections": [*report.sections, *sections]})
        except (ValidationError, TypeError, ValueError, KeyError) as exc:
            error = exc
    error_name = type(error).__name__ if error else "unknown error"
    raise ValueError(f"Translation output was invalid ({error_name}).") from None


def default_image_queries(location: str, limit: int = 5) -> list[ReportImageQuery]:
    """Create resilient category searches when the image-planning agent is unavailable."""
    categories = (
        (location, location),
        (f"{location} waterfront", f"{location} beach waterfront"),
        (f"{location} heritage", f"{location} historic temple heritage"),
        (f"{location} culture", f"{location} museum cultural landmark"),
        (f"{location} local life", f"{location} market streetscape"),
    )
    return [
        ReportImageQuery(area_name=area_name, query=query)
        for area_name, query in categories[:limit]
    ]


async def plan_report_images(
    report: ReportSpec,
    *,
    location: str,
    limit: int,
    llm: Any,
    usage_sink: Callable[[int], None] | None = None,
) -> list[ReportImageQuery]:
    """Ask the writer model for specific, evidence-related Commons image searches."""
    context = {
        "report_title": report.title,
        "section_titles": [section.title for section in report.sections[:12]],
        "source_titles": [source.title for source in report.sources[:30]],
    }
    prompt = (
        f"Plan exactly {limit} visually distinctive travel images for a report about "
        f"{location}. Choose real, specifically named places or areas supported by the report "
        "context. The first item must be the strongest landscape-oriented cover image. Avoid "
        "generic phrases such as 'travel landmark'. Each query must be concise and suitable "
        "for Wikimedia Commons search, normally '<specific place> <city>'. Do not invent "
        "places. Return ImageQueryPlan.\n"
        f"Report context: {json.dumps(context)}"
    )
    structured = prepare_structured_model(llm, ImageQueryPlan)
    error: Exception | None = None
    for attempt in range(2):
        repair = f"\nReturn exactly {limit} unique named places." if attempt else ""
        try:
            raw = await _invoke_structured(structured, prompt + repair)
            parsed, tokens = unwrap_structured(raw)
            if usage_sink is not None:
                usage_sink(tokens)
            plan = (
                parsed
                if isinstance(parsed, ImageQueryPlan)
                else ImageQueryPlan.model_validate(parsed)
            )
            unique: list[ReportImageQuery] = []
            seen: set[str] = set()
            for item in plan.items:
                key = item.area_name.strip().casefold()
                if not key or key in seen or not item.query.strip():
                    continue
                seen.add(key)
                query = item.query.strip()
                if location.casefold() not in query.casefold():
                    query = f"{query} {location}"
                unique.append(
                    ReportImageQuery(area_name=item.area_name.strip(), query=query)
                )
                if len(unique) >= limit:
                    return unique
            if unique:
                for fallback in default_image_queries(location, limit):
                    key = fallback.area_name.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    unique.append(fallback)
                    if len(unique) >= limit:
                        break
                return unique
            raise ValueError("image plan contained no usable queries")
        except (ValidationError, TypeError, ValueError, KeyError) as exc:
            error = exc
    error_name = type(error).__name__ if error else "unknown error"
    raise ValueError(f"Image plan was invalid ({error_name}).") from None


async def add_report_images(
    report: ReportSpec,
    *,
    queries: list[ReportImageQuery],
    asset_directory: Path,
    limit: int = 5,
) -> tuple[ReportSpec, list[str]]:
    """Attach licensed Commons images, local assets, citations, and attribution."""
    warnings: list[str] = []
    sources = list(report.sources)
    blocks: list[ImageBlock] = []
    used_pages: set[str] = set()
    asset_directory.mkdir(parents=True, exist_ok=True)
    for planned in queries[:limit]:
        try:
            results = await search_images(planned.query, limit=4)
        except Exception as exc:
            warnings.append(
                f"Image search for '{planned.area_name}' failed ({type(exc).__name__})."
            )
            continue
        index = len(blocks) + 1
        slug = re.sub(r"[^a-z0-9]+", "-", planned.area_name.lower()).strip("-")
        selected: tuple[Any, Path] | None = None
        last_error: Exception | None = None
        for candidate in results:
            if str(candidate.page_url) in used_pages:
                continue
            thumbnail_path = str(candidate.thumbnail_url).lower().split("?", 1)[0]
            extension = ".png" if thumbnail_path.endswith(".png") else ".jpg"
            output = asset_directory / f"{index:02d}-{slug or 'place'}{extension}"
            try:
                path = await download_image(str(candidate.thumbnail_url), output)
            except Exception as exc:
                last_error = exc
                continue
            if not _ensure_docx_compatible_image(path):
                last_error = ValueError("image format is not compatible with Word")
                continue
            selected = (candidate, path)
            break
        if selected is None:
            detail = f" ({type(last_error).__name__})" if last_error else ""
            warnings.append(
                f"No Word-compatible licensed image found for '{planned.area_name}'{detail}."
            )
            continue
        image, path = selected
        used_pages.add(str(image.page_url))
        source_id = f"S{len(sources) + 1}"
        attribution = f"{image.license}; creator: {image.artist}"
        sources.append(
            Source(
                id=source_id,
                url=image.page_url,
                title=f"Image: {planned.area_name} — {image.title}",
                snippet=attribution,
                credibility_score=0.8,
            )
        )
        blocks.append(
            ImageBlock(
                path=str(path),
                area_name=planned.area_name,
                caption=f"{image.description} • {attribution}",
                alt_text=image.description,
                source_ids=[source_id],
            )
        )
    if not blocks:
        if not warnings:
            warnings.append("No licensed Wikimedia Commons images were found.")
        return report, warnings

    sections = list(report.sections)
    if len(blocks) > 1:
        weather_index = next(
            (
                index
                for index, section in enumerate(sections)
                if "weather" in section.title.lower() or "best time" in section.title.lower()
            ),
            -1,
        )
        gallery_index = weather_index + 1 if weather_index >= 0 else min(1, len(sections))
        sections.insert(
            gallery_index,
            Section(
                title="Visual highlights",
                blocks=[ImageGalleryBlock(images=blocks[1:5])],
            ),
        )
    return (
        report.model_copy(
            update={"cover_image": blocks[0], "sections": sections, "sources": sources}
        ),
        warnings,
    )
