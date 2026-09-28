"""Licensed image discovery and download through Wikimedia Commons."""

from __future__ import annotations

import html
import re
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from autoresearcher.errors import ToolError

_WIKIMEDIA_HEADERS = {"User-Agent": "AutoResearcher/0.1 research@example.invalid"}


class ImageSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=2, ge=1, le=5)
    timeout: float = Field(default=20, gt=0, le=60)


class ImageResult(BaseModel):
    """A freely licensed Commons image with attribution metadata."""

    title: str
    page_url: HttpUrl
    image_url: HttpUrl
    thumbnail_url: HttpUrl
    license: str
    artist: str
    description: str = ""


class DownloadImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    url: HttpUrl
    output: str = Field(min_length=1)
    timeout: float = Field(default=20, gt=0, le=60)
    max_bytes: int = Field(default=8_000_000, ge=10_000, le=20_000_000)

    @field_validator("url")
    @classmethod
    def only_wikimedia_uploads(cls, value: HttpUrl) -> HttpUrl:
        if value.host not in {"upload.wikimedia.org", "thumb.wikimedia.org"}:
            raise ValueError(
                "image downloads must use upload.wikimedia.org or thumb.wikimedia.org"
            )
        return value


def _plain_metadata(value: object, default: str) -> str:
    raw = value.get("value") if isinstance(value, dict) else value
    if not isinstance(raw, str) or not raw.strip():
        return default
    without_tags = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(html.unescape(without_tags).split())


def _free_license(value: str) -> bool:
    normalized = value.upper().replace("-", " ")
    return any(
        marker in normalized
        for marker in ("CC BY", "CC0", "PUBLIC DOMAIN", "PD ", "GFDL")
    )


async def search_images(
    query: str,
    *,
    limit: int = 2,
    timeout: float = 20,
) -> list[ImageResult]:
    """Search Wikimedia Commons for freely licensed JPEG/PNG travel images."""
    inputs = ImageSearchInput(query=query, limit=limit, timeout=timeout)
    try:
        async with httpx.AsyncClient(
            timeout=inputs.timeout,
            headers=_WIKIMEDIA_HEADERS,
        ) as client:
            response = await client.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": inputs.query,
                    "gsrnamespace": 6,
                    "gsrlimit": min(inputs.limit * 4, 20),
                    "prop": "imageinfo|info",
                    "iiprop": "url|mime|extmetadata",
                    "iiurlwidth": 1400,
                    "iiextmetadatafilter": (
                        "LicenseShortName|Artist|Credit|ImageDescription"
                    ),
                    "inprop": "url",
                    "format": "json",
                    "formatversion": 2,
                },
            )
            response.raise_for_status()
            pages = response.json().get("query", {}).get("pages", [])
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ToolError(f"Image search failed ({type(exc).__name__}).") from None

    results: list[ImageResult] = []
    for page in pages:
        info_rows = page.get("imageinfo") or []
        if not info_rows:
            continue
        info = info_rows[0]
        if info.get("mime") not in {"image/jpeg", "image/png"}:
            continue
        metadata = info.get("extmetadata") or {}
        license_name = _plain_metadata(metadata.get("LicenseShortName"), "")
        if not _free_license(license_name):
            continue
        thumbnail = info.get("thumburl") or info.get("url")
        image_url = info.get("url")
        page_url = page.get("canonicalurl") or page.get("fullurl")
        if not all((thumbnail, image_url, page_url)):
            continue
        results.append(
            ImageResult.model_validate(
                {
                    "title": str(page.get("title", "Image")).removeprefix("File:"),
                    "page_url": page_url,
                    "image_url": image_url,
                    "thumbnail_url": thumbnail,
                    "license": license_name,
                    "artist": _plain_metadata(metadata.get("Artist"), "Unknown creator"),
                    "description": _plain_metadata(
                        metadata.get("ImageDescription"),
                        str(page.get("title", "Travel image")).removeprefix("File:"),
                    ),
                }
            )
        )
        if len(results) >= inputs.limit:
            break
    return results


async def download_image(
    url: str,
    output: str | Path,
    *,
    timeout: float = 20,
    max_bytes: int = 8_000_000,
) -> Path:
    """Download a bounded JPEG/PNG image to a caller-selected local path."""
    inputs = DownloadImageInput.model_validate(
        {"url": url, "output": str(output), "timeout": timeout, "max_bytes": max_bytes}
    )
    try:
        async with httpx.AsyncClient(
            timeout=inputs.timeout,
            follow_redirects=True,
            headers=_WIKIMEDIA_HEADERS,
        ) as client:
            response = await client.get(str(inputs.url))
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(f"Image download failed ({type(exc).__name__}).") from None
    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    if content_type not in {"image/jpeg", "image/png"}:
        raise ToolError(f"Unsupported image content type: {content_type or 'unknown'}")
    if len(response.content) > inputs.max_bytes:
        raise ToolError(f"Image exceeds the {inputs.max_bytes}-byte safety limit")
    path = Path(inputs.output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return path
