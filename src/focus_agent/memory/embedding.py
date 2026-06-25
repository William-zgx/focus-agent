from __future__ import annotations

import hashlib
from typing import Any

from ..core.repo_call import has_repo_method
from ..retrieval import RetrievalDocument, RetrievalIndex
from .embedding_factory import (
    _create_auto_memory_embedding_provider,
    _create_ollama_embedding_provider,
    _create_openai_compatible_embedding_provider,
    _default_model_client_kwargs,
    _memory_embedding_backend,
    _normalize_provider_name,
    _ollama_embedding_base_url,
    _ollama_embedding_dimensions,
    _ollama_embedding_model,
    _openai_compatible_embedding_dimensions,
    _openai_compatible_embedding_model,
    _openai_compatible_fallback_configured,
    _settings_environ,
    create_memory_embedding_provider,
)
from .embedding_policy import should_embed_memory
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
    MemoryEmbeddingError,
    OllamaEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    _coerce_embedding,
    _decode_json_response,
    _deterministic_embedding,
    _embedding_http_client,
    _extract_ollama_embeddings,
    _ollama_model_available,
    _ollama_native_base_url,
    _ollama_pull_model,
    _validate_dimensions,
    ollama_embedding_install_hint,
    shared_sync_http_client,
)
from .embedding_repository_adapter import (
    MemoryEmbeddingPayload,
    _existing_memory_embedding_content_hash,
    _metadata_content_hash,
    _upsert_memory_embedding,
)
from .models import MemoryRecord, MemoryStatus


class MemoryEmbeddingService:
    def __init__(
        self,
        *,
        repository: Any | None = None,
        embedding_repository: Any | None = None,
        provider: EmbeddingProvider | str | None = None,
        embedder: EmbeddingProvider | None = None,
        retrieval_index: RetrievalIndex | None = None,
        batch_size: int = 32,
    ):
        self.repository = repository if repository is not None else embedding_repository
        self.embedding_repository = self.repository
        provider_object = embedder or (provider if not isinstance(provider, str) else None)
        if provider_object is None:
            raise EmbeddingProviderConfigError(
                "MemoryEmbeddingService requires an embedding provider."
            )
        self.provider = provider_object
        self.retrieval_index = retrieval_index
        self.batch_size = max(1, int(batch_size))
        self.backend = provider if isinstance(provider, str) else self.provider.provider_id

    @classmethod
    def from_repository(cls, repository: object | None) -> MemoryEmbeddingService | None:
        del repository
        return None

    def embed_text(self, text: str) -> list[float]:
        vectors = self.provider.embed_texts([text])
        return list(vectors[0]) if vectors else []

    def embed_record(self, record: MemoryRecord) -> bool:
        result = self.ensure_embedding(record)
        return result.get("status") == "written"

    def ensure_embedding(self, record: MemoryRecord) -> dict[str, object]:
        if not should_embed_memory(record):
            return {
                "memory_id": record.memory_id,
                "status": "skipped",
                "reason": "inactive_memory",
            }
        text = memory_embedding_text(record)
        if not text:
            return {
                "memory_id": record.memory_id,
                "status": "skipped",
                "reason": "empty_text",
            }
        content_hash = memory_embedding_content_hash(text)
        existing_hash = _existing_memory_embedding_content_hash(
            self.repository,
            memory_id=record.memory_id,
            namespace=record.namespace,
            provider_id=self.provider.provider_id,
            model_id=self.provider.model_id,
        )
        if existing_hash == content_hash:
            return {
                "memory_id": record.memory_id,
                "status": "skipped",
                "content_hash": content_hash,
                "reason": "content_hash_match",
            }
        if self.repository is None:
            return {
                "memory_id": record.memory_id,
                "status": "skipped",
                "content_hash": content_hash,
                "reason": "embedding_repository_unavailable",
            }

        vector = self.embed_text(text)
        retrieval_written = self._upsert_retrieval_index_best_effort(
            record, text, vector, content_hash
        )
        payload = MemoryEmbeddingPayload(
            memory_id=record.memory_id,
            namespace=record.namespace,
            provider_id=self.provider.provider_id,
            model_id=self.provider.model_id,
            dimensions=self.provider.dimensions,
            content_hash=content_hash,
            embedding=vector,
            metadata={
                "text_hash": content_hash,
                "source": "memory_embedding_service",
            },
        )
        embedding_written = _upsert_memory_embedding(self.repository, payload)
        if not embedding_written:
            return {
                "memory_id": record.memory_id,
                "status": "written" if retrieval_written else "skipped",
                "content_hash": content_hash,
                "reason": "embedding_repository_unavailable",
            }
        return {
            "memory_id": record.memory_id,
            "status": "written",
            "content_hash": content_hash,
        }

    def embed_records(self, records: list[MemoryRecord]) -> dict[str, int]:
        attempted = 0
        embedded = 0
        skipped = 0
        failed = 0
        for record in records:
            if not should_embed_memory(record):
                skipped += 1
                continue
            attempted += 1
            try:
                if self.embed_record(record):
                    embedded += 1
                else:
                    skipped += 1
            except Exception:  # noqa: BLE001
                failed += 1
        return {
            "attempted": attempted,
            "embedded": embedded,
            "skipped": skipped,
            "failed": failed,
        }

    def backfill(self, *, limit: int = 1000) -> dict[str, int]:
        if not has_repo_method(self.repository, "list_records"):
            return {"attempted": 0, "embedded": 0, "skipped": 0, "failed": 0}
        from ..repositories.memory_repository import MemoryListQuery

        records = self.repository.list_records(
            MemoryListQuery(status=MemoryStatus.ACTIVE.value, limit=limit)
        )
        return self.embed_records(records)

    def _upsert_retrieval_index_best_effort(
        self,
        record: MemoryRecord,
        text: str,
        vector: list[float],
        content_hash: str,
    ) -> bool:
        if self.retrieval_index is None:
            return False
        try:
            self.retrieval_index.upsert(
                RetrievalDocument(
                    collection="focus_memory",
                    doc_id=f"memory:{record.memory_id}",
                    source_id=record.memory_id,
                    text=text,
                    vector=vector,
                    fields={
                        "source_type": "memory",
                        "memory_id": record.memory_id,
                        "namespace": tuple(record.namespace),
                        "status": record.status.value,
                        "kind": record.kind.value,
                        "scope": record.scope.value,
                        "visibility": record.visibility.value,
                        "user_id": record.user_id,
                        "root_thread_id": record.root_thread_id,
                        "source_thread_id": record.source_thread_id,
                        "source_branch_id": record.source_branch_id,
                        "provider_id": self.provider.provider_id,
                        "model_id": self.provider.model_id,
                        "content_hash": content_hash,
                    },
                )
            )
            return True
        except Exception:  # noqa: BLE001
            return False


def create_memory_embedding_service(
    settings: Any,
    *,
    repository: object | None = None,
    retrieval_index: RetrievalIndex | None = None,
) -> MemoryEmbeddingService | None:
    provider = create_memory_embedding_provider(settings)
    if provider is None:
        return None
    return MemoryEmbeddingService(
        repository=repository,
        provider=provider,
        retrieval_index=retrieval_index,
        batch_size=int(getattr(settings, "agent_memory_embedding_batch_size", 32)),
    )


def memory_embedding_text(record: MemoryRecord) -> str:
    parts = [
        str(record.summary or "").strip(),
        str(record.content or "").strip(),
        " ".join(record.tags),
        " ".join(record.evidence_refs),
    ]
    return "\n".join(part for part in parts if part).strip()


def memory_embedding_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.12g}" for value in vector) + "]"


__compat_exports = (
    _coerce_embedding,
    _create_auto_memory_embedding_provider,
    _create_ollama_embedding_provider,
    _create_openai_compatible_embedding_provider,
    _decode_json_response,
    _default_model_client_kwargs,
    _deterministic_embedding,
    _embedding_http_client,
    _existing_memory_embedding_content_hash,
    _extract_ollama_embeddings,
    _memory_embedding_backend,
    _metadata_content_hash,
    _normalize_provider_name,
    _ollama_embedding_base_url,
    _ollama_embedding_dimensions,
    _ollama_embedding_model,
    _ollama_model_available,
    _ollama_native_base_url,
    _ollama_pull_model,
    _openai_compatible_embedding_dimensions,
    _openai_compatible_embedding_model,
    _openai_compatible_fallback_configured,
    _settings_environ,
    _upsert_memory_embedding,
    _validate_dimensions,
    shared_sync_http_client,
)


__all__ = [
    "DEFAULT_OLLAMA_BASE_URL",
    "DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS",
    "DEFAULT_OLLAMA_EMBEDDING_MODEL",
    "DEFAULT_OLLAMA_PULL_TIMEOUT_SECONDS",
    "DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_DIMENSIONS",
    "DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL",
    "DeterministicTestEmbeddingProvider",
    "EmbeddingProvider",
    "EmbeddingProviderConfigError",
    "MemoryEmbeddingError",
    "MemoryEmbeddingPayload",
    "MemoryEmbeddingService",
    "OllamaEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "create_memory_embedding_provider",
    "create_memory_embedding_service",
    "memory_embedding_content_hash",
    "memory_embedding_text",
    "ollama_embedding_install_hint",
    "should_embed_memory",
    "vector_literal",
]
