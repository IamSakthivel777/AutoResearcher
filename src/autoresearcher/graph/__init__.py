"""Research graph nodes and state."""

from __future__ import annotations

import importlib
import warnings

from langchain_core._api.deprecation import suppress_langchain_deprecation_warning

# LangGraph 0.x emits this pending-deprecation warning from a lazy cache import.
# Keep the match exact so other dependency warnings remain visible.
warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change.*",
)

with suppress_langchain_deprecation_warning():
    importlib.import_module("langgraph.cache.base")
