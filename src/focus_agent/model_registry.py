from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from langchain.chat_models import init_chat_model

from .config import ConfiguredModel, ModelCatalogConfig, ProviderConfig, Settings


_BUILTIN_MODEL_CATALOG = ModelCatalogConfig(
    providers=(
        ProviderConfig(
            id="anthropic",
            label="Anthropic",
            backend_provider="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
        ),
        ProviderConfig(
            id="moonshot",
            label="Moonshot AI",
            backend_provider="openai",
            aliases=("kimi",),
            base_url_env="MOONSHOT_BASE_URL",
            base_url_default="https://api.moonshot.cn/v1",
            api_key_env="MOONSHOT_API_KEY",
        ),
        ProviderConfig(
            id="ollama",
            label="Ollama",
            backend_provider="openai",
            base_url_env="OLLAMA_BASE_URL",
            base_url_default="http://127.0.0.1:11434/v1",
            api_key_env="OLLAMA_API_KEY",
            api_key_default="ollama",
        ),
        ProviderConfig(
            id="openai",
            label="OpenAI Compatible",
            backend_provider="openai",
            base_url_env="OPENAI_BASE_URL",
            api_key_env="OPENAI_API_KEY",
        ),
    ),
    models=(
        ConfiguredModel(
            id="anthropic:claude-3-5-sonnet-latest",
            label="Claude 3.5 Sonnet",
        ),
        ConfiguredModel(
            id="openai:deepseek-chat",
            label="DeepSeek Chat",
            supports_thinking=True,
            default_thinking_enabled=False,
            thinking_enable_extra_body_type="enabled",
        ),
        ConfiguredModel(
            id="openai:deepseek-reasoner",
            label="DeepSeek Reasoner",
            supports_thinking=True,
            default_thinking_enabled=True,
            thinking_disable_switch_model="deepseek-chat",
        ),
        ConfiguredModel(
            id="openai:gpt-4.1",
            label="GPT-4.1",
        ),
        ConfiguredModel(
            id="openai:gpt-4.1-mini",
            label="GPT-4.1 Mini",
        ),
        ConfiguredModel(
            id="moonshot:kimi-k2.6",
            label="Kimi K2.6",
            supports_thinking=True,
            default_thinking_enabled=True,
            no_temperature=True,
            thinking_disable_extra_body_type="disabled",
        ),
    ),
)


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


def _merged_provider_configs(settings: Settings | None = None) -> dict[str, ProviderConfig]:
    merged = {item.id: item for item in _BUILTIN_MODEL_CATALOG.providers}
    if settings is None:
        return merged
    for item in settings.model_catalog.providers:
        merged[item.id] = item
    return merged


def _merged_model_configs(settings: Settings | None = None) -> dict[str, ConfiguredModel]:
    merged = {
        canonical_model_id(item.id, settings=settings): item
        for item in _BUILTIN_MODEL_CATALOG.models
    }
    if settings is None:
        return merged
    for item in settings.model_catalog.models:
        merged[canonical_model_id(item.id, settings=settings)] = item
    return merged


def _provider_alias_map(settings: Settings | None = None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for provider in _merged_provider_configs(settings).values():
        for alias in provider.aliases:
            aliases[alias] = provider.id
    return aliases


def normalize_provider_name(value: str, *, settings: Settings | None = None) -> str:
    lowered = value.strip().lower()
    return _provider_alias_map(settings).get(lowered, lowered)


def parse_model_id(model_id: str, *, settings: Settings | None = None) -> tuple[str, str]:
    raw = str(model_id or "").strip()
    if not raw:
        raise ValueError("Model identifier cannot be empty.")
    if ":" in raw:
        provider, name = raw.split(":", 1)
    else:
        provider, name = "openai", raw
    provider = normalize_provider_name(provider, settings=settings)
    name = name.strip()
    if not name:
        raise ValueError(f"Model identifier {raw!r} is missing a model name.")
    return provider, name


def canonical_model_id(model_id: str, *, settings: Settings | None = None) -> str:
    provider, name = parse_model_id(model_id, settings=settings)
    return f"{provider}:{name}"


def _configured_model(model_id: str, *, settings: Settings | None = None) -> ConfiguredModel | None:
    return _merged_model_configs(settings).get(canonical_model_id(model_id, settings=settings))


def _merge_request_kwargs(*items: Mapping[str, object] | None) -> dict[str, object]:
    merged: dict[str, object] = {}
    for item in items:
        if not item:
            continue
        for key, value in item.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, Mapping):
                merged[key] = _merge_request_kwargs(existing, value)
            else:
                merged[key] = value
    return merged


def _effective_thinking_mode(configured: ConfiguredModel, thinking_mode: str | None) -> str:
    normalized = str(thinking_mode or "").strip().lower()
    if normalized in {"enabled", "disabled"}:
        return normalized
    return "enabled" if configured.default_thinking_enabled else ""


def _request_kwargs_for_model(
    configured: ConfiguredModel,
    *,
    thinking_mode: str,
) -> dict[str, object]:
    profile_kwargs = _merge_request_kwargs(configured.request_kwargs)
    if thinking_mode == "enabled":
        profile_kwargs = _merge_request_kwargs(
            profile_kwargs,
            configured.thinking_enabled_request_kwargs,
        )
    elif thinking_mode == "disabled":
        profile_kwargs = _merge_request_kwargs(
            profile_kwargs,
            configured.thinking_disabled_request_kwargs,
        )

    if configured.reasoning_effort and thinking_mode != "disabled":
        profile_kwargs = _merge_request_kwargs(
            profile_kwargs,
            {"reasoning_effort": configured.reasoning_effort},
        )
    if thinking_mode == "enabled" and configured.thinking_enable_extra_body_type:
        profile_kwargs = _merge_request_kwargs(
            profile_kwargs,
            {"extra_body": {"thinking": {"type": configured.thinking_enable_extra_body_type}}},
        )
    if thinking_mode == "disabled" and configured.thinking_disable_extra_body_type:
        profile_kwargs = _merge_request_kwargs(
            profile_kwargs,
            {"extra_body": {"thinking": {"type": configured.thinking_disable_extra_body_type}}},
        )
    return profile_kwargs


def supports_thinking_mode(model_id: str, *, settings: Settings | None = None) -> bool:
    configured = _configured_model(model_id, settings=settings)
    return bool(configured.supports_thinking) if configured is not None else False


def default_thinking_enabled(model_id: str, *, settings: Settings | None = None) -> bool:
    configured = _configured_model(model_id, settings=settings)
    return bool(configured.default_thinking_enabled) if configured is not None else False


def _provider_label(provider: str, *, settings: Settings | None = None) -> str:
    provider_config = _merged_provider_configs(settings).get(provider)
    if provider_config and provider_config.label:
        return provider_config.label
    return provider.replace("_", " ").title()


def _model_label(model_id: str, *, settings: Settings | None = None) -> str:
    configured = _configured_model(model_id, settings=settings)
    if configured and configured.label:
        return configured.label
    _, name = parse_model_id(model_id, settings=settings)
    return name


def build_model_catalog(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
) -> list[ModelOption]:
    del environ
    ordered_ids: list[str] = [settings.model, *settings.model_choices]
    deduped_ids: list[str] = []
    seen: set[str] = set()
    default_model_id = canonical_model_id(settings.model, settings=settings)
    for model_id in ordered_ids:
        normalized = canonical_model_id(model_id, settings=settings)
        if not normalized or normalized in seen:
            continue
        deduped_ids.append(normalized)
        seen.add(normalized)

    options: list[ModelOption] = []
    for model_id in deduped_ids:
        provider, name = parse_model_id(model_id, settings=settings)
        provider_label = _provider_label(provider, settings=settings)
        model_label = _model_label(model_id, settings=settings)
        options.append(
            ModelOption(
                id=model_id,
                provider=provider,
                provider_label=provider_label,
                name=name,
                label=f"{model_label} · {provider_label}",
                is_default=model_id == default_model_id,
                supports_thinking=supports_thinking_mode(model_id, settings=settings),
                default_thinking_enabled=default_thinking_enabled(model_id, settings=settings),
            )
        )
    return options


def resolve_model_config(
    model_id: str,
    *,
    thinking_mode: str | None = None,
    environ: Mapping[str, str] | None = None,
    settings: Settings | None = None,
) -> ResolvedModelConfig:
    env = (
        environ
        if environ is not None
        else (settings.resolved_env if settings is not None and settings.resolved_env else os.environ)
    )
    provider, name = parse_model_id(model_id, settings=settings)
    provider_config = _merged_provider_configs(settings).get(provider)
    backend_provider = provider_config.backend_provider if provider_config and provider_config.backend_provider else provider
    client_kwargs: dict[str, str] = {}
    request_kwargs: dict[str, object] = {}

    if provider_config is not None:
        if provider_config.base_url_env or provider_config.base_url_default:
            base_url = (
                env.get(provider_config.base_url_env)
                if provider_config.base_url_env
                else None
            ) or provider_config.base_url_default
            if base_url:
                client_kwargs["base_url"] = base_url
        if provider_config.api_key_env or provider_config.api_key_default:
            api_key = (
                env.get(provider_config.api_key_env)
                if provider_config.api_key_env
                else None
            ) or provider_config.api_key_default
            if api_key:
                client_kwargs["api_key"] = api_key

    configured = _configured_model(f"{provider}:{name}", settings=settings)
    if configured is not None:
        effective_thinking_mode = _effective_thinking_mode(configured, thinking_mode)
        request_kwargs = _request_kwargs_for_model(
            configured,
            thinking_mode=effective_thinking_mode,
        )
        if effective_thinking_mode == "disabled":
            name = (
                configured.thinking_disabled_model_name
                or configured.thinking_disable_switch_model
                or name
            )

    return ResolvedModelConfig(
        model_id=f"{provider}:{name}",
        provider=provider,
        backend_provider=backend_provider,
        model_name=name,
        client_kwargs=client_kwargs,
        request_kwargs=request_kwargs,
    )


def _effective_temperature(
    model_id: str,
    temperature: float,
    *,
    settings: Settings | None = None,
) -> float | None:
    configured = _configured_model(model_id, settings=settings)
    if configured is not None and configured.no_temperature:
        return None
    return temperature


def _needs_openai_reasoning_passthrough(
    model_id: str,
    *,
    settings: Settings | None = None,
) -> bool:
    configured = _configured_model(model_id, settings=settings)
    return bool(configured and configured.supports_thinking)


def create_chat_model(
    model_id: str,
    *,
    temperature: float,
    thinking_mode: str | None = None,
    settings: Settings | None = None,
):
    resolved = resolve_model_config(
        model_id,
        thinking_mode=thinking_mode,
        settings=settings,
    )
    init_kwargs: dict[str, object] = {
        **resolved.client_kwargs,
        **resolved.request_kwargs,
    }
    effective_temperature = _effective_temperature(model_id, temperature, settings=settings)
    if effective_temperature is not None:
        init_kwargs["temperature"] = effective_temperature
    if resolved.backend_provider == "openai" and (
        resolved.provider == "moonshot"
        or _needs_openai_reasoning_passthrough(model_id, settings=settings)
    ):
        from .providers.moonshot_openai import MoonshotChatOpenAI

        if resolved.provider == "moonshot":
            init_kwargs.setdefault("stream_usage", True)
        return MoonshotChatOpenAI(
            model=resolved.model_name,
            **init_kwargs,
        )
    return init_chat_model(
        f"{resolved.backend_provider}:{resolved.model_name}",
        **init_kwargs,
    )


__all__ = [
    "ModelOption",
    "ResolvedModelConfig",
    "build_model_catalog",
    "canonical_model_id",
    "create_chat_model",
    "default_thinking_enabled",
    "normalize_provider_name",
    "parse_model_id",
    "resolve_model_config",
    "supports_thinking_mode",
]
