from __future__ import annotations

import os
from typing import Any

from .embedding_providers import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS,
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    DEFAULT_OLLAMA_PULL_TIMEOUT_SECONDS,
    DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_DIMENSIONS,
    DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL,
    DeterministicTestEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingProviderConfigError,
    OllamaEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    _ollama_model_available,
    _ollama_native_base_url,
    _ollama_pull_model,
    _validate_dimensions,
    ollama_embedding_install_hint,
)


def create_memory_embedding_provider(settings: Any) -> EmbeddingProvider | None:
    backend = _memory_embedding_backend(settings)
    if backend in {"", "disabled", "none", "off"}:
        return None
    provider_id = backend
    model_id = str(
        getattr(settings, "agent_memory_embedding_model", DEFAULT_OLLAMA_EMBEDDING_MODEL)
    ).strip()
    dimensions = int(
        getattr(settings, "agent_memory_embedding_dimensions", None)
        or DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS
    )
    if provider_id == "deterministic_test":
        return DeterministicTestEmbeddingProvider(
            model_id=model_id or "deterministic-test", dimensions=dimensions
        )
    if provider_id == "ollama":
        return _create_ollama_embedding_provider(settings)
    if provider_id == "openai_compatible":
        return _create_openai_compatible_embedding_provider(
            settings,
            model_id=_openai_compatible_embedding_model(settings, model_id=model_id),
            dimensions=_openai_compatible_embedding_dimensions(
                settings,
                dimensions=dimensions,
            ),
        )
    if provider_id == "auto":
        return _create_auto_memory_embedding_provider(settings)
    raise EmbeddingProviderConfigError(f"Unknown memory embedding provider: {provider_id}")


def _memory_embedding_backend(settings: Any) -> str:
    backend = getattr(settings, "agent_memory_embedding_backend", None)
    if backend in {None, "disabled", "none", "off", ""}:
        if not bool(getattr(settings, "agent_memory_embedding_enabled", False)):
            return "disabled"
        backend = getattr(settings, "agent_memory_embedding_provider", "openai_compatible")
    return str(backend or "").strip().lower().replace("-", "_")


def _create_auto_memory_embedding_provider(settings: Any) -> EmbeddingProvider | None:
    ollama_provider = _create_ollama_embedding_provider(settings, ensure_model=False)
    fallback_configured = _openai_compatible_fallback_configured(settings)
    if _ollama_model_ready(
        settings,
        ollama_provider,
        allow_auto_pull=not fallback_configured,
    ):
        return ollama_provider

    if not fallback_configured:
        raise EmbeddingProviderConfigError(
            "Auto memory embedding provider unavailable. "
            f"Ollama model {ollama_provider.model_id!r} is not installed or Ollama is not running. "
            f"{_ollama_recovery_hint(settings, ollama_provider)}"
        )

    try:
        model_id = _openai_compatible_embedding_model(
            settings,
            model_id=str(
                getattr(settings, "agent_memory_embedding_model", DEFAULT_OLLAMA_EMBEDDING_MODEL)
                or ""
            ).strip(),
        )
        return _create_openai_compatible_embedding_provider(
            settings,
            model_id=model_id,
            dimensions=_openai_compatible_embedding_dimensions(
                settings,
                dimensions=int(
                    getattr(settings, "agent_memory_embedding_dimensions", None)
                    or DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS
                ),
            ),
        )
    except EmbeddingProviderConfigError as exc:
        raise EmbeddingProviderConfigError(
            "Auto memory embedding provider unavailable. "
            f"Ollama model {ollama_provider.model_id!r} is not installed or Ollama is not running. "
            f"{_ollama_recovery_hint(settings, ollama_provider)} "
            f"OpenAI-compatible fallback unavailable: {exc}"
        ) from exc


def _create_ollama_embedding_provider(
    settings: Any,
    *,
    ensure_model: bool = True,
) -> OllamaEmbeddingProvider:
    model_id = _ollama_embedding_model(settings)
    provider = OllamaEmbeddingProvider(
        model_id=model_id,
        dimensions=_ollama_embedding_dimensions(settings, model_id=model_id),
        base_url=_ollama_embedding_base_url(settings),
        timeout_seconds=float(getattr(settings, "agent_memory_embedding_timeout_seconds", 30.0)),
    )
    if ensure_model and _ollama_auto_pull_enabled(settings):
        _ensure_ollama_model_ready(settings, provider)
    return provider


def _ollama_model_ready(
    settings: Any,
    provider: OllamaEmbeddingProvider,
    *,
    allow_auto_pull: bool,
) -> bool:
    if _ollama_model_available(provider):
        return True
    if not allow_auto_pull or not _ollama_auto_pull_enabled(settings):
        return False
    _ollama_pull_model(
        provider,
        timeout_seconds=float(
            getattr(
                settings,
                "agent_memory_embedding_pull_timeout_seconds",
                DEFAULT_OLLAMA_PULL_TIMEOUT_SECONDS,
            )
        ),
    )
    return _ollama_model_available(provider)


def _ensure_ollama_model_ready(settings: Any, provider: OllamaEmbeddingProvider) -> None:
    if _ollama_model_ready(settings, provider, allow_auto_pull=True):
        return
    raise EmbeddingProviderConfigError(
        "Ollama memory embedding provider unavailable. "
        f"Ollama model {provider.model_id!r} is not installed or Ollama is not running. "
        f"{_ollama_recovery_hint(settings, provider)}"
    )


def _ollama_auto_pull_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "agent_memory_embedding_auto_pull", False))


def _ollama_recovery_hint(settings: Any, provider: OllamaEmbeddingProvider) -> str:
    install = f"Install it with: {ollama_embedding_install_hint(provider.model_id)}."
    if not _ollama_auto_pull_enabled(settings):
        return install
    return (
        "Auto-pull is enabled, but the model is still unavailable. "
        "Ensure Ollama is running, then retry or pull manually with: "
        f"{ollama_embedding_install_hint(provider.model_id)}."
    )


def _create_openai_compatible_embedding_provider(
    settings: Any,
    *,
    model_id: str,
    dimensions: int,
) -> OpenAICompatibleEmbeddingProvider:
    api_key_env = str(
        getattr(settings, "agent_memory_embedding_api_key_env", "OPENAI_API_KEY") or ""
    ).strip()
    api_key = str(getattr(settings, "agent_memory_embedding_api_key", "") or "").strip()
    inherited_client_kwargs = _default_model_client_kwargs(settings)
    if not api_key and api_key_env:
        api_key = _settings_environ(settings).get(api_key_env, "").strip()
    if not api_key:
        api_key = str(inherited_client_kwargs.get("api_key") or "").strip()
    if not api_key:
        key_hint = f" env {api_key_env!r}" if api_key_env else ""
        raise EmbeddingProviderConfigError(
            f"OpenAI-compatible embedding API key{key_hint} is not set."
        )
    base_url = getattr(settings, "agent_memory_embedding_base_url", None)
    if not base_url:
        base_url = inherited_client_kwargs.get("base_url")
    return OpenAICompatibleEmbeddingProvider(
        model_id=model_id or DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL,
        dimensions=dimensions,
        api_key=api_key,
        base_url=str(base_url).strip() if base_url else None,
        timeout_seconds=float(getattr(settings, "agent_memory_embedding_timeout_seconds", 30.0)),
    )


def _settings_environ(settings: Any) -> dict[str, str]:
    resolved = getattr(settings, "resolved_env", None)
    if isinstance(resolved, dict) and resolved:
        return {str(key): str(value) for key, value in resolved.items()}
    return dict(os.environ)


def _openai_compatible_fallback_configured(settings: Any) -> bool:
    env = _settings_environ(settings)
    env_backend = _normalize_provider_name(env.get("AGENT_MEMORY_EMBEDDING_BACKEND"))
    env_provider = _normalize_provider_name(env.get("AGENT_MEMORY_EMBEDDING_PROVIDER"))
    if env_backend == "openai_compatible" or env_provider == "openai_compatible":
        return True
    for key in (
        "AGENT_MEMORY_EMBEDDING_BASE_URL",
        "AGENT_MEMORY_EMBEDDING_API_KEY",
        "AGENT_MEMORY_EMBEDDING_API_KEY_ENV",
    ):
        if str(env.get(key) or "").strip():
            return True
    explicit_model = str(env.get("AGENT_MEMORY_EMBEDDING_MODEL") or "").strip()
    if explicit_model and explicit_model not in {
        DEFAULT_OLLAMA_EMBEDDING_MODEL,
        "embedding-gemma",
    }:
        return True
    base_url = str(getattr(settings, "agent_memory_embedding_base_url", "") or "").strip()
    if base_url and "ollama" not in base_url.lower() and "11434" not in base_url:
        return True
    if str(getattr(settings, "agent_memory_embedding_api_key", "") or "").strip():
        return True
    api_key_env = str(getattr(settings, "agent_memory_embedding_api_key_env", "") or "").strip()
    if api_key_env and api_key_env != "OPENAI_API_KEY":
        return True
    return False


def _openai_compatible_embedding_model(settings: Any, *, model_id: str) -> str:
    env = _settings_environ(settings)
    explicit_model = str(env.get("AGENT_MEMORY_EMBEDDING_MODEL") or "").strip()
    model = str(model_id or explicit_model or "").strip()
    if model and model not in {DEFAULT_OLLAMA_EMBEDDING_MODEL, "embedding-gemma"}:
        return model
    return DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL


def _openai_compatible_embedding_dimensions(settings: Any, *, dimensions: int) -> int:
    env = _settings_environ(settings)
    if str(env.get("AGENT_MEMORY_EMBEDDING_DIMENSIONS") or "").strip():
        return _validate_dimensions(dimensions)
    if dimensions in {0, DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS}:
        return DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_DIMENSIONS
    return _validate_dimensions(dimensions)


def _normalize_provider_name(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _default_model_client_kwargs(settings: Any) -> dict[str, str]:
    try:
        from ..model_registry import resolve_model_config

        resolved = resolve_model_config(
            str(getattr(settings, "model", "") or ""),
            settings=settings,
        )
    except Exception:
        return {}
    return {str(key): str(value) for key, value in resolved.client_kwargs.items()}


def _ollama_embedding_model(settings: Any) -> str:
    model = str(getattr(settings, "agent_memory_embedding_model", "") or "").strip()
    if not model or model == "text-embedding-3-small":
        return DEFAULT_OLLAMA_EMBEDDING_MODEL
    return model


def _ollama_embedding_dimensions(settings: Any, *, model_id: str) -> int:
    dimensions = int(getattr(settings, "agent_memory_embedding_dimensions", None) or 0)
    if model_id == DEFAULT_OLLAMA_EMBEDDING_MODEL and dimensions in {0, 1536}:
        return DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS
    return _validate_dimensions(dimensions or DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS)


def _ollama_embedding_base_url(settings: Any) -> str:
    base_url = str(getattr(settings, "agent_memory_embedding_base_url", "") or "").strip()
    if not base_url:
        base_url = _settings_environ(settings).get("OLLAMA_BASE_URL", "").strip()
    return _ollama_native_base_url(base_url or DEFAULT_OLLAMA_BASE_URL)


__all__ = ["create_memory_embedding_provider"]
