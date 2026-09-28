"""Typed Tavily search with a key-free DuckDuckGo fallback."""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr

from autoresearcher.errors import SearchError


class WebSearchInput(BaseModel):
    """Validated input to the web search tool."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    query: str = Field(min_length=2, max_length=1_000)
    max_results: int = Field(default=5, ge=1, le=10)
    timeout: float = Field(default=15.0, gt=0, le=60)


class SearchResult(BaseModel):
    """One result produced by a search backend."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    title: str = Field(min_length=1)
    url: HttpUrl
    snippet: str = ""
    score: float | None = Field(default=None, ge=0, le=1)


class SearchResponse(BaseModel):
    """Search results plus non-fatal fallback information."""

    results: list[SearchResult]
    provider: str
    warning: str | None = None


async def _tavily_search(inputs: WebSearchInput, key: str) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=inputs.timeout) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": inputs.query,
                "max_results": inputs.max_results,
                "search_depth": "advanced",
            },
        )
        response.raise_for_status()
        payload = response.json()
    return [
        SearchResult(
            title=item.get("title") or "Untitled result",
            url=item["url"],
            snippet=item.get("content") or item.get("snippet") or "",
            score=item.get("score"),
        )
        for item in payload.get("results", [])[: inputs.max_results]
        if item.get("url")
    ]


def _duckduckgo_search(inputs: WebSearchInput) -> list[SearchResult]:
    from ddgs import DDGS

    raw_results: list[dict[str, Any]] = list(
        DDGS(timeout=int(inputs.timeout)).text(inputs.query, max_results=inputs.max_results)
    )
    return [
        SearchResult(
            title=item.get("title") or "Untitled result",
            url=item["href"],
            snippet=item.get("body") or "",
        )
        for item in raw_results
        if item.get("href")
    ]


async def _duckduckgo_search_async(inputs: WebSearchInput) -> list[SearchResult]:
    """Run DDGS off-loop without leaving a process-blocking executor thread behind."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[list[SearchResult]] = loop.create_future()

    def deliver_result(value: list[SearchResult] | BaseException) -> None:
        if future.done():
            return
        if isinstance(value, BaseException):
            future.set_exception(value)
        else:
            future.set_result(value)

    def target() -> None:
        try:
            value: list[SearchResult] | BaseException = _duckduckgo_search(inputs)
        except BaseException as exc:
            value = exc
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(deliver_result, value)

    threading.Thread(
        target=target,
        name="autoresearcher-ddgs",
        daemon=True,
    ).start()
    return await asyncio.wait_for(future, timeout=inputs.timeout + 1)


async def web_search(
    query: str,
    *,
    api_key: SecretStr | str | None = None,
    max_results: int = 5,
    timeout: float = 15.0,
) -> SearchResponse:
    """Search the web using Tavily, falling back to DuckDuckGo without exposing secrets."""
    inputs = WebSearchInput(query=query, max_results=max_results, timeout=timeout)
    key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
    warning: str | None = None
    if key:
        try:
            results = await _tavily_search(inputs, key)
            return SearchResponse(results=results, provider="tavily")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            warning = f"Tavily search failed ({type(exc).__name__}); used DuckDuckGo fallback."
    try:
        results = await _duckduckgo_search_async(inputs)
        return SearchResponse(results=results, provider="duckduckgo", warning=warning)
    except Exception as exc:
        raise SearchError(f"Web search failed ({type(exc).__name__}).") from None
