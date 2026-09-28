"""Safe, bounded page fetching and text extraction."""

from __future__ import annotations

import ipaddress
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from autoresearcher.errors import ToolError


class FetchPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    url: HttpUrl
    timeout: float = Field(default=15.0, gt=0, le=60)
    max_bytes: int = Field(default=2_000_000, ge=1_000, le=10_000_000)


class PageContent(BaseModel):
    """Clean text and metadata fetched from a public HTTP page."""

    url: HttpUrl
    title: str
    text: str
    content_type: str


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self._ignored_depth:
            return
        self.parts.append(value)
        if self._in_title:
            self.title_parts.append(value)


def _ensure_public_url(url: HttpUrl) -> None:
    host = urlparse(str(url)).hostname or ""
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ToolError("fetch_page only accepts public HTTP(S) URLs")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ToolError("fetch_page blocks private, loopback, and link-local addresses")


async def fetch_page(
    url: str,
    *,
    timeout: float = 15.0,
    max_bytes: int = 2_000_000,
) -> PageContent:
    """Fetch a public page and return bounded visible text without scripts or styles."""
    inputs = FetchPageInput.model_validate(
        {"url": url, "timeout": timeout, "max_bytes": max_bytes}
    )
    _ensure_public_url(inputs.url)
    try:
        async with httpx.AsyncClient(
            timeout=inputs.timeout,
            follow_redirects=True,
            headers={"User-Agent": "AutoResearcher/0.1 (+https://github.com/autoresearcher)"},
        ) as client:
            response = await client.get(str(inputs.url))
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not fetch page ({type(exc).__name__}).") from None
    if len(response.content) > inputs.max_bytes:
        raise ToolError(f"Page exceeds the {inputs.max_bytes}-byte safety limit")

    content_type = response.headers.get("content-type", "text/plain").split(";", 1)[0]
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _HTMLTextExtractor()
        parser.feed(response.text)
        title = " ".join(parser.title_parts) or (urlparse(str(response.url)).hostname or "Page")
        text = "\n".join(parser.parts)
    elif content_type.startswith("text/") or content_type in {
        "application/json",
        "application/xml",
    }:
        title = urlparse(str(response.url)).hostname or "Page"
        text = response.text
    else:
        raise ToolError(f"Unsupported page content type: {content_type}")
    return PageContent.model_validate(
        {
            "url": str(response.url),
            "title": title[:500],
            "text": text[: inputs.max_bytes],
            "content_type": content_type,
        }
    )
