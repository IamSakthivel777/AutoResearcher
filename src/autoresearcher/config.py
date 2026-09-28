"""Secure settings and model-routing configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Role = Literal["planner", "worker", "critic", "writer"]
Provider = Literal["anthropic", "openai", "gemini"]


class Settings(BaseSettings):
    """Runtime settings with constructor > environment > ``.env`` precedence."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("gemini_api_key", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
        repr=False,
    )
    search_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("search_api_key", "TAVILY_API_KEY"),
        repr=False,
    )
    pinecone_api_key: SecretStr | None = Field(default=None, repr=False)

    models: dict[Role, str] = Field(default_factory=dict)
    max_subagents: int = Field(default=8, ge=1, le=64)
    max_critic_loops: int = Field(default=2, ge=0, le=10)
    max_tool_calls: int = Field(default=6, ge=1, le=50)
    token_budget: int = Field(default=100_000, ge=1_000)
    task_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    llm_timeout_seconds: float = Field(default=180.0, gt=0, le=600)

    @field_validator(
        "anthropic_api_key",
        "openai_api_key",
        "gemini_api_key",
        "search_api_key",
        "pinecone_api_key",
        mode="before",
    )
    @classmethod
    def empty_keys_are_unset(cls, value: object) -> object:
        """Treat empty variables in ``.env.example`` as missing keys."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def key_for(self, provider: Provider) -> SecretStr | None:
        """Return the secret for an LLM provider without revealing it."""
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
        }[provider]

    @property
    def configured_providers(self) -> tuple[Provider, ...]:
        """List configured LLM providers in deterministic fallback order."""
        providers: list[Provider] = []
        for provider in ("anthropic", "openai", "gemini"):
            if self.key_for(provider) is not None:
                providers.append(provider)
        return tuple(providers)

    @classmethod
    def from_env_file(cls, path: str | Path, **overrides: object) -> Settings:
        """Load a specific dotenv file, primarily for applications and tests."""
        return cls(_env_file=path, **overrides)  # type: ignore[call-arg, arg-type]
