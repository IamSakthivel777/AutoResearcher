"""Centralized role-to-provider model routing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from pydantic import SecretStr

from autoresearcher.config import Provider, Role, Settings
from autoresearcher.errors import ConfigurationError, MissingAPIKeyError

# Model identifiers are intentionally centralized so upgrades are one-line changes.
DEFAULT_MODEL_IDS: dict[Provider, dict[Role, str]] = {
    "anthropic": {
        "planner": "claude-sonnet-5",
        "worker": "claude-fable-5",
        "critic": "claude-sonnet-5",
        "writer": "claude-sonnet-5",
    },
    "openai": {
        "planner": "gpt-5",
        "worker": "gpt-5-mini",
        "critic": "gpt-5",
        "writer": "gpt-5",
    },
    "gemini": {
        "planner": "gemini-3.8-flash",
        "worker": "gemini-3.5-flash-lite",
        "critic": "gemini-3.8-flash",
        "writer": "gemini-3.8-flash",
    },
}

DEFAULT_PROVIDER: dict[Role, Provider] = {
    "planner": "anthropic",
    "worker": "gemini",
    "critic": "anthropic",
    "writer": "anthropic",
}

PROVIDER_ALIASES: dict[str, Provider] = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "google": "gemini",
}


@dataclass(frozen=True)
class LLMRoute:
    """Resolved provider route without any secret material."""

    provider: Provider
    model: str
    warning: str | None = None


def _parse_requested(value: str, role: Role) -> tuple[Provider, str | None]:
    provider_text, separator, model = value.partition(":")
    provider = PROVIDER_ALIASES.get(provider_text.strip().lower())
    if provider is None:
        inferred = next(
            (
                candidate
                for prefix, candidate in (
                    ("claude-", "anthropic"),
                    ("gpt-", "openai"),
                    ("o1", "openai"),
                    ("o3", "openai"),
                    ("o4", "openai"),
                    ("gemini-", "gemini"),
                )
                if value.lower().startswith(prefix)
            ),
            None,
        )
        if inferred is None:
            raise ConfigurationError(
                f"Unknown model provider '{provider_text}' for role '{role}'. "
                "Use claude, openai, or gemini."
            )
        return cast(Provider, inferred), value
    if separator and not model.strip():
        raise ConfigurationError(f"A model id is required after '{provider_text}:'")
    return provider, model.strip() or None


def resolve_route(role: Role, settings: Settings) -> LLMRoute:
    """Resolve a role to an available provider, model id, and optional warning."""
    if not settings.configured_providers:
        raise MissingAPIKeyError

    requested_value = settings.models.get(role)
    if requested_value:
        requested_provider, requested_model = _parse_requested(requested_value, role)
    else:
        requested_provider = DEFAULT_PROVIDER[role]
        requested_model = None

    if settings.key_for(requested_provider) is not None:
        return LLMRoute(
            provider=requested_provider,
            model=requested_model or DEFAULT_MODEL_IDS[requested_provider][role],
        )

    provider = settings.configured_providers[0]
    warning = (
        f"The requested {requested_provider} provider for {role} is not configured; "
        f"using {provider} instead."
    )
    return LLMRoute(provider, DEFAULT_MODEL_IDS[provider][role], warning)


def _anthropic_builder(*, model: str, api_key: str, timeout: float) -> Any:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model_name=model,
        api_key=SecretStr(api_key),
        # Structured invocations are retried by the shared Tenacity wrapper.
        max_retries=0,
        timeout=timeout,
        stop=None,
    )


def _openai_builder(*, model: str, api_key: str, timeout: float) -> Any:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=SecretStr(api_key),
        # Avoid multiplying SDK retries by application-level retries.
        max_retries=0,
        timeout=timeout,
    )


def _gemini_builder(*, model: str, api_key: str, timeout: float) -> Any:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        api_key=SecretStr(api_key),
        retries=0,
        request_timeout=timeout,
    )


ProviderBuilder = Callable[..., Any]
PROVIDER_BUILDERS: dict[Provider, ProviderBuilder] = {
    "anthropic": _anthropic_builder,
    "openai": _openai_builder,
    "gemini": _gemini_builder,
}


def get_llm(
    role: Role,
    settings: Settings,
    *,
    warnings: list[str] | None = None,
    builders: dict[Provider, ProviderBuilder] | None = None,
) -> Any:
    """Return a LangChain chat model for ``role``, falling back when necessary."""
    route = resolve_route(role, settings)
    if route.warning and warnings is not None:
        warnings.append(route.warning)
    secret = settings.key_for(route.provider)
    if secret is None:  # pragma: no cover - resolve_route guarantees this
        raise MissingAPIKeyError
    builder = (builders or PROVIDER_BUILDERS)[route.provider]
    try:
        return builder(
            model=route.model,
            api_key=secret.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
        )
    except Exception as exc:
        raise ConfigurationError(
            f"Could not initialize the {route.provider} model '{route.model}': "
            f"{type(exc).__name__}"
        ) from None
