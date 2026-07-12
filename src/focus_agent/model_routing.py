"""Four-axis model routing.

Inspired by pi/opencode's ``Route = Protocol + Endpoint + Auth + Framing``
model, this module defines a :class:`ModelRoute` dataclass that captures
everything needed to talk to a model provider, plus a :func:`resolve_route`
helper that derives a route from the model catalog's provider configuration.

Axes
----
1. **Protocol** -- wire format for the chat completions request
   (``openai_compatible``, ``anthropic_messages``, ``google_gemini``,
   ``openai_responses``).
2. **Endpoint** -- base URL.
3. **Auth** -- authentication scheme and credential configuration.
4. **Framing** -- response transfer encoding (``sse``, ``json``, ``binary``).

The route is independent of any particular HTTP client; consumers (HTTP
client factories, streaming adapters, test fixtures) consume the frozen
dataclass to build request-sending primitives.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from .config_parts.catalog_config_types import ProviderConfig

ModelProtocol = Literal[
    "openai_compatible",
    "anthropic_messages",
    "google_gemini",
    "openai_responses",
]
AuthType = Literal["api_key", "bearer", "oauth", "none"]
Framing = Literal["sse", "json", "binary"]

# Mapping from backend_provider -> protocol. The "openai" backend covers
# OpenAI, DeepSeek, Moonshot, MiMo, Ollama, vLLM, Ollama, etc. -- any
# provider that speaks the OpenAI Chat Completions wire format.
_PROVIDER_PROTOCOL_MAP: dict[str, ModelProtocol] = {
    "openai": "openai_compatible",
    "anthropic": "anthropic_messages",
    "google": "google_gemini",
    "google_genai": "google_gemini",
    "openai_responses": "openai_responses",
}


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """A fully resolved four-axis route to a model provider.

    Attributes
    ----------
    protocol:
        Wire protocol used to speak to the provider.
    endpoint:
        Base URL for API requests (e.g. ``"https://api.openai.com/v1"``).
    auth_type:
        Authentication scheme. ``"api_key"`` means the provider expects the
        key in a provider-specific header/query param; ``"bearer"`` means
        standard ``Authorization: Bearer <token>``; ``"oauth"`` means a
        bearer token obtained via OAuth; ``"none"`` means unauthenticated
        (e.g. a local Ollama endpoint with no key configured).
    auth_config:
        Provider-specific auth parameters. Typically contains ``"api_key"``
        (the resolved secret), ``"header_name"`` (if non-standard), etc.
    framing:
        Response transfer framing. Default ``"sse"`` for streaming.
    extra_headers:
        Additional HTTP headers to attach to every request.
    timeout_seconds:
        Total request timeout in seconds.
    chunk_timeout_seconds:
        Idle timeout between streamed chunks in seconds.
    """

    protocol: ModelProtocol
    endpoint: str
    auth_type: AuthType
    auth_config: dict[str, Any] = field(default_factory=dict)
    framing: Framing = "sse"
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    chunk_timeout_seconds: float = 30.0


def _resolve_endpoint(
    provider_config: ProviderConfig,
    environ: Mapping[str, str] | None = None,
) -> str:
    env = environ if environ is not None else os.environ
    base_url: str | None = None
    if provider_config.base_url_env:
        base_url = env.get(provider_config.base_url_env)
    if not base_url:
        base_url = provider_config.base_url_default
    return (base_url or "").rstrip("/")


def _resolve_api_key(
    provider_config: ProviderConfig,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    env = environ if environ is not None else os.environ
    key: str | None = None
    if provider_config.api_key_env:
        key = env.get(provider_config.api_key_env)
    if not key:
        key = provider_config.api_key_default
    return key


def _infer_protocol(backend_provider: str) -> ModelProtocol:
    """Map a backend_provider string to a ModelProtocol."""
    normalized = (backend_provider or "").strip().lower()
    return _PROVIDER_PROTOCOL_MAP.get(normalized, "openai_compatible")


def _infer_auth_type(api_key: str | None, protocol: ModelProtocol) -> AuthType:
    if not api_key:
        return "none"
    if protocol == "anthropic_messages":
        return "api_key"  # uses x-api-key header
    return "bearer"


def resolve_route(
    model_id: str,
    provider_config: ProviderConfig,
    *,
    environ: Mapping[str, str] | None = None,
    extra_headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 60.0,
    chunk_timeout_seconds: float = 30.0,
) -> ModelRoute:
    """Build a :class:`ModelRoute` from a model id and provider config.

    Parameters
    ----------
    model_id:
        Canonical model identifier ``"provider:model-name"``. Currently
        unused beyond validation (kept for future per-model endpoint
        overrides) but accepted so call sites can pass it uniformly.
    provider_config:
        The resolved :class:`ProviderConfig` for this model's provider.
    environ:
        Environment mapping to read credentials/base URLs from. Defaults
        to ``os.environ``.
    extra_headers:
        Optional extra HTTP headers to attach to every request.
    timeout_seconds:
        Total request timeout.
    chunk_timeout_seconds:
        Idle-chunk timeout for streaming.

    Returns
    -------
    ModelRoute
        A frozen dataclass ready for consumption by HTTP client factories.
    """
    del model_id  # reserved for future per-model overrides
    backend_provider = provider_config.backend_provider or provider_config.id
    protocol = _infer_protocol(backend_provider)
    endpoint = _resolve_endpoint(provider_config, environ=environ)
    api_key = _resolve_api_key(provider_config, environ=environ)
    auth_type = _infer_auth_type(api_key, protocol)

    auth_config: dict[str, Any] = {}
    if api_key:
        auth_config["api_key"] = api_key
        if protocol == "anthropic_messages":
            auth_config["header_name"] = "x-api-key"
        elif auth_type == "bearer":
            auth_config["header_name"] = "Authorization"
            auth_config["header_prefix"] = "Bearer"

    return ModelRoute(
        protocol=protocol,
        endpoint=endpoint,
        auth_type=auth_type,
        auth_config=auth_config,
        framing="sse",
        extra_headers=dict(extra_headers or {}),
        timeout_seconds=timeout_seconds,
        chunk_timeout_seconds=chunk_timeout_seconds,
    )


__all__ = [
    "AuthType",
    "Framing",
    "ModelProtocol",
    "ModelRoute",
    "resolve_route",
]
