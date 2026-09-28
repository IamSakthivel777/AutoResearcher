"""Validated intermediate representation for report rendering."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from autoresearcher.models import Source, StrictModel


class CitedBlock(StrictModel):
    """Shared validation for blocks that may contain factual content."""

    factual: bool = True
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def factual_content_is_cited(self) -> CitedBlock:
        if self.factual and not self.source_ids:
            raise ValueError("factual report blocks require at least one source_id")
        return self


class HeadingBlock(StrictModel):
    type: Literal["heading"] = "heading"
    text: str = Field(min_length=1)
    level: int = Field(default=2, ge=1, le=4)


class ParagraphBlock(CitedBlock):
    type: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1)


class BulletsBlock(CitedBlock):
    type: Literal["bullets"] = "bullets"
    items: list[str] = Field(min_length=1)


class NumberedBlock(CitedBlock):
    type: Literal["numbered"] = "numbered"
    items: list[str] = Field(min_length=1)


class TableBlock(CitedBlock):
    type: Literal["table"] = "table"
    headers: list[str] = Field(min_length=1)
    rows: list[list[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def rows_match_header_width(self) -> TableBlock:
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("each table row must match the number of headers")
        return self


class ChecklistBlock(CitedBlock):
    type: Literal["checklist"] = "checklist"
    items: list[str] = Field(min_length=1)


class CalloutBlock(CitedBlock):
    type: Literal["callout"] = "callout"
    kind: Literal["info", "tip", "warning"] = "info"
    text: str = Field(min_length=1)


class DayPlanEntry(StrictModel):
    time: str
    activity: str
    details: str = ""
    source_ids: list[str] = Field(min_length=1)


class DayPlanBlock(StrictModel):
    type: Literal["day_plan"] = "day_plan"
    day: int = Field(ge=1)
    title: str
    entries: list[DayPlanEntry] = Field(min_length=1)


class ImageBlock(CitedBlock):
    type: Literal["image"] = "image"
    path: str = Field(min_length=1)
    area_name: str = ""
    caption: str = Field(min_length=1)
    alt_text: str = ""
    width_inches: float = Field(default=6.2, gt=0, le=7)


class ImageGalleryBlock(StrictModel):
    type: Literal["image_gallery"] = "image_gallery"
    images: list[ImageBlock] = Field(min_length=1, max_length=4)


class PageBreakBlock(StrictModel):
    type: Literal["page_break"] = "page_break"


ReportBlock = Annotated[
    HeadingBlock
    | ParagraphBlock
    | BulletsBlock
    | NumberedBlock
    | TableBlock
    | ChecklistBlock
    | CalloutBlock
    | DayPlanBlock
    | ImageBlock
    | ImageGalleryBlock
    | PageBreakBlock,
    Field(discriminator="type"),
]


class Section(StrictModel):
    """A named report section containing renderable blocks."""

    title: str = Field(min_length=1)
    blocks: list[ReportBlock] = Field(default_factory=list)


class ReportSpec(StrictModel):
    """Complete, source-grounded report representation."""

    title: str = Field(min_length=1)
    subtitle: str = ""
    report_date: date = Field(default_factory=date.today)
    metadata: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    cover_image: ImageBlock | None = None
    sections: list[Section] = Field(min_length=1)
    sources: list[Source] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_known_sources(self) -> ReportSpec:
        known = {source.id for source in self.sources}
        if len(known) != len(self.sources):
            raise ValueError("source ids must be unique")
        referenced: set[str] = set()
        if self.cover_image is not None:
            referenced.update(self.cover_image.source_ids)
        for section in self.sections:
            for block in section.blocks:
                if isinstance(block, DayPlanBlock):
                    for entry in block.entries:
                        referenced.update(entry.source_ids)
                elif isinstance(block, ImageGalleryBlock):
                    for image in block.images:
                        referenced.update(image.source_ids)
                elif isinstance(block, CitedBlock):
                    referenced.update(block.source_ids)
        unknown = sorted(referenced - known)
        if unknown:
            raise ValueError(f"report references unknown source ids: {', '.join(unknown)}")
        return self
