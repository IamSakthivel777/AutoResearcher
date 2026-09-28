"""Package-specific exceptions with safe, actionable messages."""


class AutoResearcherError(Exception):
    """Base class for AutoResearcher failures."""


class MissingAPIKeyError(AutoResearcherError):
    """Raised when no supported LLM provider is configured."""

    def __init__(self) -> None:
        super().__init__(
            "No LLM API key is configured. Set one of ANTHROPIC_API_KEY, "
            "OPENAI_API_KEY, GEMINI_API_KEY, or GOOGLE_API_KEY."
        )


class ConfigurationError(AutoResearcherError):
    """Raised for invalid model routing or runtime configuration."""


class PlanningError(AutoResearcherError):
    """Raised when the planner cannot return a valid research plan."""


class SearchError(AutoResearcherError):
    """Raised when all configured search backends fail."""


class ToolError(AutoResearcherError):
    """Raised when a validated plain-Python tool cannot complete safely."""


class SyncInAsyncError(AutoResearcherError):
    """Raised when the synchronous API is called from an event loop."""
