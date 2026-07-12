from __future__ import annotations

import inspect
import logging
from collections.abc import Callable

from ..config import Settings
from ..core.repo_call import has_repo_method
from ..memory.embedding import MemoryEmbeddingError, create_memory_embedding_provider
from .runtime_types import RuntimeMemoryEmbeddingSetup

logger = logging.getLogger("focus_agent.runtime")


def _resolve_memory_embedding_setup(
    settings: Settings,
    *,
    provider_factory: Callable[[Settings], object | None] | None = None,
    dimensions_resolver: Callable[..., int] | None = None,
    configured_resolver: Callable[[Settings], bool] | None = None,
) -> RuntimeMemoryEmbeddingSetup:
    provider_factory = provider_factory or create_memory_embedding_provider
    dimensions_resolver = dimensions_resolver or _memory_embedding_schema_dimensions
    configured_resolver = configured_resolver or _memory_embedding_configured
    provider: object | None = None
    backend_error: str | None = None
    try:
        provider = provider_factory(settings)
    except MemoryEmbeddingError as exc:
        backend_error = str(exc)
        logger.warning("Memory embedding backend unavailable: %s", exc)
    dimensions = dimensions_resolver(settings, provider=provider)
    try:
        settings.agent_memory_embedding_dimensions = dimensions
    except Exception:  # pragma: no cover - Settings is mutable in production.
        pass
    return RuntimeMemoryEmbeddingSetup(
        provider=provider,
        backend_error=backend_error,
        dimensions=dimensions,
        memory_embeddings_enabled=configured_resolver(settings),
    )


def _memory_embedding_schema_dimensions(settings: Settings, *, provider: object | None) -> int:
    provider_dimensions = getattr(provider, "dimensions", None)
    if provider_dimensions:
        return max(1, int(provider_dimensions))
    configured = int(getattr(settings, "agent_memory_embedding_dimensions", 1536) or 1536)
    if configured > 0:
        return configured
    model_id = str(getattr(settings, "agent_memory_embedding_model", "") or "").strip().lower()
    backend = str(getattr(settings, "agent_memory_embedding_backend", "") or "").strip().lower()
    provider_id = (
        str(getattr(settings, "agent_memory_embedding_provider", "") or "").strip().lower()
    )
    if (
        model_id in {"embeddinggemma", "embedding-gemma"}
        or backend == "ollama"
        or provider_id == "ollama"
    ):
        return 768
    return 1536


def _setup_memory_repository_if_available(
    component: object,
    *,
    settings: Settings,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup,
) -> None:
    if not has_repo_method(component, "setup"):
        return
    signature = inspect.signature(component.setup)
    if not signature.parameters:
        component.setup()
        return
    component.setup(
        dimensions=memory_embedding_setup.dimensions,
        vector_index=getattr(settings, "agent_memory_vector_index_enabled", False),
        memory_embeddings_enabled=memory_embedding_setup.memory_embeddings_enabled,
        pgvector_extension_mode=getattr(
            settings,
            "agent_memory_pgvector_extension_mode",
            "auto_create",
        ),
    )


def _memory_embedding_configured(settings: Settings) -> bool:
    backend = str(getattr(settings, "agent_memory_embedding_backend", "") or "").strip().lower()
    if backend and backend not in {"disabled", "none", "off"}:
        return True
    if bool(getattr(settings, "agent_memory_embedding_enabled", False)):
        return True
    return (
        str(getattr(settings, "agent_memory_vector_search_mode", "off")).strip().lower() == "hybrid"
    )
