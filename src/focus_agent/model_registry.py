from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from langchain.chat_models import init_chat_model

from .config import Settings


_PROVIDER_ALIASES = {
    "kimi": "moonshot",
}

_PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "moonshot": "Moonshot AI",
    "ollama": "Ollama",
    "openai": "OpenAI Compatible",
}

_MODEL_LABELS = {
    "claude-3-5-sonnet-latest": "Claude 3.5 Sonnet",
    "deepseek-chat": "DeepSeek Chat",
    "deepseek-reasoner": "DeepSeek Reasoner",
    "gpt-4.1": "GPT-4.1",
    "gpt-4.1-mini": "GPT-4.1 Mini",
    "kimi-k2.5": "Kimi K2.5",
}


@dataclass(frozen=True, slots=True)
class ModelOption:
    id: str
    provider: str
    provider_label: str
    name: str
    label: str
    is_default: bool = False
    supports_thinking: bool = False
    default_thinking_enabled: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedModelConfig:
    model_id: str
    provider: str
    backend_provider: str
    model_name: str
    client_kwargs: dict[str, str]
    request_kwargs: dict[str, object]


def supports_thinking_mode(model_id: str) -> bool:
    provider, name = parse_model_id(model_id)
    return (provider == "moonshot" and name == "kimi-k2.5") or (
        provider == "openai" and name in {"deepseek-chat", "deepseek-reasoner"}
    )


def default_thinking_enabled(model_id: str) -> bool:
    provider, name = parse_model_id(model_id)
    return (provider == "moonshot" and name == "kimi-k2.5") or (
        provider == "openai" and name == "deepseek-reasoner"
    )


def normalize_provider_name(value: str) -> str:
    lowered = value.strip().lower()
    return _PROVIDER_ALIASES.get(lowered, lowered)


def parse_model_id(model_id: str) -> tuple[str, str]:
    raw = str(model_id or "").strip()
    if not raw:
        raise ValueError("Model identifier cannot be empty.")
    if ":" in raw:
        provider, name = raw.split(":", 1)
    else:
        provider, name = "openai", raw
    provider = normalize_provider_name(provider)
    name = name.strip()
    if not name:
        raise ValueError(f"Model identifier {raw!r} is missing a model name.")
    return provider, name


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider.replace("_", " ").title())


def _model_label(name: str) -> str:
    return _MODEL_LABELS.get(name, name)


def build_model_catalog(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
) -> list[ModelOption]:
    del environ
    ordered_ids: list[str] = [settings.model, *settings.model_choices]
    deduped_ids: list[str] = []
    seen: set[str] = set()
    for model_id in ordered_ids:
        normalized = str(model_id or "").strip()
        if not normalized or normalized in seen:
            continue
        deduped_ids.append(normalized)
        seen.add(normalized)

    options: list[ModelOption] = []
    for model_id in deduped_ids:
        provider, name = parse_model_id(model_id)
        provider_label = _provider_label(provider)
        model_label = _model_label(name)
        options.append(
            ModelOption(
                id=model_id,
                provider=provider,
                provider_label=provider_label,
                name=name,
                label=f"{model_label} · {provider_label}",
                is_default=model_id == settings.model,
                supports_thinking=supports_thinking_mode(model_id),
                default_thinking_enabled=default_thinking_enabled(model_id),
            )
        )
    return options


def resolve_model_config(
    model_id: str,
    *,
    thinking_mode: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ResolvedModelConfig:
    env = environ or os.environ
    provider, name = parse_model_id(model_id)
    backend_provider = provider
    client_kwargs: dict[str, str] = {}
    request_kwargs: dict[str, object] = {}

    if provider == "moonshot":
        backend_provider = "openai"
        base_url = (
            env.get("MOONSHOT_BASE_URL")
            or env.get("KIMI_BASE_URL")
            or "https://api.moonshot.cn/v1"
        )
        api_key = env.get("MOONSHOT_API_KEY") or env.get("KIMI_API_KEY")
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
        if name == "kimi-k2.5" and thinking_mode == "disabled":
            request_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    elif provider == "ollama":
        backend_provider = "openai"
        base_url = env.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
        api_key = env.get("OLLAMA_API_KEY") or "ollama"
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
    elif provider == "openai":
        base_url = env.get("OPENAI_BASE_URL")
        api_key = env.get("OPENAI_API_KEY")
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
        if name == "deepseek-chat" and thinking_mode == "enabled":
            request_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        if name == "deepseek-reasoner" and thinking_mode == "disabled":
            name = "deepseek-chat"
    elif provider == "anthropic":
        api_key = env.get("ANTHROPIC_API_KEY")
        if api_key:
            client_kwargs["api_key"] = api_key

    return ResolvedModelConfig(
        model_id=f"{provider}:{name}",
        provider=provider,
        backend_provider=backend_provider,
        model_name=name,
        client_kwargs=client_kwargs,
        request_kwargs=request_kwargs,
    )


def _effective_temperature(model_id: str, temperature: float) -> float | None:
    provider, name = parse_model_id(model_id)
    if provider == "moonshot" and name == "kimi-k2.5":
        return None
    return temperature


def create_chat_model(model_id: str, *, temperature: float, thinking_mode: str | None = None):
    resolved = resolve_model_config(model_id, thinking_mode=thinking_mode)
    init_kwargs: dict[str, object] = {
        **resolved.client_kwargs,
        **resolved.request_kwargs,
    }
    effective_temperature = _effective_temperature(model_id, temperature)
    if effective_temperature is not None:
        init_kwargs["temperature"] = effective_temperature
    return init_chat_model(
        f"{resolved.backend_provider}:{resolved.model_name}",
        **init_kwargs,
    )


__all__ = [
    "ModelOption",
    "ResolvedModelConfig",
    "build_model_catalog",
    "create_chat_model",
    "default_thinking_enabled",
    "normalize_provider_name",
    "parse_model_id",
    "resolve_model_config",
    "supports_thinking_mode",
]
