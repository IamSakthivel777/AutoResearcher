"""Typed plain-Python tools wrapped by MCP servers in Phase 3."""

from autoresearcher.tools.calculations import estimate_budget, estimate_travel_time
from autoresearcher.tools.docx import render_docx
from autoresearcher.tools.images import download_image, search_images
from autoresearcher.tools.itinerary import build_itinerary
from autoresearcher.tools.memory import embed_and_store, retrieve_similar
from autoresearcher.tools.places import search_places
from autoresearcher.tools.search import SearchResponse, SearchResult, web_search
from autoresearcher.tools.weather import get_weather_forecast
from autoresearcher.tools.web import fetch_page

__all__ = [
    "SearchResponse",
    "SearchResult",
    "build_itinerary",
    "download_image",
    "embed_and_store",
    "estimate_budget",
    "estimate_travel_time",
    "fetch_page",
    "get_weather_forecast",
    "render_docx",
    "retrieve_similar",
    "search_images",
    "search_places",
    "web_search",
]
