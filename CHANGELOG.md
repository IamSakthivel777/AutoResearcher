# Changelog

## 0.1.1 - 2026-09-28

- Upgrade to the LangChain 1.x / LangGraph 1.x dependency line so installation coexists with
  applications that already use modern LangChain.

## Unreleased - Phase 2

- Compile the research flow as a LangGraph with `Send` worker fan-out and reducer-based fan-in.
- Add deterministic clarification, evidence critic revisions, bounded failure handling, and
  token/tool/sub-agent limits.
- Add page, place, weather, travel-time, budget, local retrieval, itinerary, and DOCX tools.
- Add offline tests for parallelism, critic loops, citation enforcement, and priority tools.
- Add sourced trip weather and seasonal guidance, multilingual highlights, and attributed
  Wikimedia Commons images.
- Add explicit travel-date parsing, OpenAI function-calling schemas, a five-place image-planning
  agent, and a named two-column DOCX image gallery.
- Add internal installation, package integration, TestPyPI, and PyPI publishing guides.

## 0.1.0 - 2026-09-28

- Scaffold the package and its typed public API.
- Add secure settings resolution and LLM provider fallback.
- Add the Phase 1 planner, web search, and cited DOCX pipeline.
