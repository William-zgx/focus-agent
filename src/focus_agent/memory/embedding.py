from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
import urllib.error
from typing import Any, Protocol
from urllib.request import Request, urlopen

from .models import MemoryRecord, MemoryStatus


class MemoryEmbeddingError(RuntimeError):
    """Raised when memory embedding generation fails."""


class EmbeddingProviderConfigError(MemoryEmbeddingError):
    """Raised when memory embedding provider configuration is invalid."""


class EmbeddingProvider(Protocol):
    provider_id: str
    model_id: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingPayload:
    memory_id: str
    namespace: tuple[str, ...]
    provider_id: str
    model_id: str
    dimensions: int
    content_hash: str
    embedding: list[float]
    metadata: dict[str, object]


class DeterministicTestEmbeddingProvider:
    provider_id = "deterministic_test"

    def __init__(self, *, model_id: str = "deterministic-test", dimensions: int = 1536):
        self.model_id = model_id
        self.dimensions = _validate_dimensions(dimensions)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_deterministic_embedding(text, dimensions=self.dimensions) for text in texts]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed(list(texts))

    def embed_text(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_text(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed(list(texts))


class OpenAICompatibleEmbeddingProvider:
    provider_id = "openai_compatible"

    def __init__(
        self,
        *,
        dimensions: int,
        api_key: str,
        model: str | None = None,
        model_id: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.model_id = (model or model_id or "text-embedding-3-small").strip()
        self.dimensions = _validate_dimensions(dimensions)
        self.api_key = api_key.strip()
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        if not self.api_key:
            raise EmbeddingProviderConfigError(
                "OpenAI-compatible embedding provider requires an API key."
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.model_id,
            "input": texts,
            "dimensions": self.dimensions,
        }
        request = Request(
            f"{self.base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise MemoryEmbeddingError("embedding provider request failed") from exc

        items = decoded.get("data") if isinstance(decoded, dict) else None
        if not isinstance(items, list) or len(items) != len(texts):
            raise MemoryEmbeddingError("embedding provider returned an invalid response shape.")
        vectors: list[list[float]] = []
        for item in sorted(items, key=lambda value: int(value.get("index", 0))):
            vector = item.get("embedding") if isinstance(item, dict) else None
            vectors.append(_coerce_embedding(vector, dimensions=self.dimensions))
        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed(list(texts))

    def embed_text(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_text(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed(list(texts))


class MemoryEmbeddingService:
    def __init__(
        self,
        *,
        repository: Any | None = None,
        embedding_repository: Any | None = None,
        provider: EmbeddingProvider | str | None = None,
        embedder: EmbeddingProvider | None = None,
        batch_size: int = 32,
    ):
        self.repository = repository if repository is not None else embedding_repository
        self.embedding_repository = self.repository
        provider_object = embedder or (provider if not isinstance(provider, str) else None)
        if provider_object is None:
            raise EmbeddingProviderConfigError("MemoryEmbeddingService requires an embedding provider.")
        self.provider = provider_object
        self.batch_size = max(1, int(batch_size))
        self.backend = provider if isinstance(provider, str) else self.provider.provider_id

    @classmethod
    def from_repository(cls, repository: object | None) -> "MemoryEmbeddingService | None":
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
        if not _upsert_memory_embedding(self.repository, payload):
            return {
                "memory_id": record.memory_id,
                "status": "skipped",
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
        list_records = getattr(self.repository, "list_records", None)
        if not callable(list_records):
            return {"attempted": 0, "embedded": 0, "skipped": 0, "failed": 0}
        from ..repositories.memory_repository import MemoryListQuery

        records = list_records(MemoryListQuery(status=MemoryStatus.ACTIVE.value, limit=limit))
        return self.embed_records(records)


def create_memory_embedding_provider(settings: Any) -> EmbeddingProvider | None:
    backend = _memory_embedding_backend(settings)
    if backend in {"", "disabled", "none", "off"}:
        return None
    provider_id = backend
    model_id = str(getattr(settings, "agent_memory_embedding_model", "text-embedding-3-small")).strip()
    dimensions = int(getattr(settings, "agent_memory_embedding_dimensions", None) or 1536)
    if provider_id == "deterministic_test":
        return DeterministicTestEmbeddingProvider(model_id=model_id or "deterministic-test", dimensions=dimensions)
    if provider_id == "openai_compatible":
        api_key_env = str(getattr(settings, "agent_memory_embedding_api_key_env", "OPENAI_API_KEY") or "").strip()
        api_key = str(getattr(settings, "agent_memory_embedding_api_key", "") or "").strip()
        if not api_key and api_key_env:
            api_key = _settings_environ(settings).get(api_key_env, "").strip()
            if not api_key:
                raise EmbeddingProviderConfigError(
                    f"OpenAI-compatible embedding API key env {api_key_env!r} is not set."
                )
        base_url = getattr(settings, "agent_memory_embedding_base_url", None)
        return OpenAICompatibleEmbeddingProvider(
            model_id=model_id or "text-embedding-3-small",
            dimensions=dimensions,
            api_key=api_key,
            base_url=str(base_url).strip() if base_url else None,
            timeout_seconds=float(getattr(settings, "agent_memory_embedding_timeout_seconds", 30.0)),
        )
    raise EmbeddingProviderConfigError(f"Unknown memory embedding provider: {provider_id}")


def create_memory_embedding_service(
    settings: Any,
    *,
    repository: object | None = None,
) -> MemoryEmbeddingService | None:
    provider = create_memory_embedding_provider(settings)
    if provider is None:
        return None
    return MemoryEmbeddingService(
        repository=repository,
        provider=provider,
        batch_size=int(getattr(settings, "agent_memory_embedding_batch_size", 32)),
    )


def _memory_embedding_backend(settings: Any) -> str:
    backend = getattr(settings, "agent_memory_embedding_backend", None)
    if backend in {None, "disabled", "none", "off", ""}:
        if not bool(getattr(settings, "agent_memory_embedding_enabled", False)):
            return "disabled"
        backend = getattr(settings, "agent_memory_embedding_provider", "openai_compatible")
    return str(backend or "").strip().lower().replace("-", "_")


def _settings_environ(settings: Any) -> dict[str, str]:
    resolved = getattr(settings, "resolved_env", None)
    if isinstance(resolved, dict) and resolved:
        return {str(key): str(value) for key, value in resolved.items()}
    return dict(os.environ)


def _existing_memory_embedding_content_hash(
    repository: object | None,
    *,
    memory_id: str,
    namespace: tuple[str, ...],
    provider_id: str,
    model_id: str,
) -> str | None:
    if repository is None:
        return None

    get_embedding = getattr(repository, "get_memory_embedding", None)
    if callable(get_embedding):
        try:
            return _metadata_content_hash(get_embedding(memory_id=memory_id))
        except TypeError:
            return _metadata_content_hash(get_embedding(memory_id))

    list_metadata = getattr(repository, "list_embedding_metadata", None)
    if not callable(list_metadata):
        return None

    offset = 0
    batch_size = 500
    while True:
        try:
            rows = list_metadata(
                namespace=namespace,
                provider_id=provider_id,
                model_id=model_id,
                limit=batch_size,
                offset=offset,
            )
        except TypeError:
            from ..repositories.memory_repository import MemoryEmbeddingListQuery

            rows = list_metadata(
                MemoryEmbeddingListQuery(
                    namespace=namespace,
                    provider_id=provider_id,
                    model_id=model_id,
                    limit=batch_size,
                    offset=offset,
                )
            )
        if not rows:
            return None
        for row in rows:
            if getattr(row, "memory_id", None) == memory_id or (
                isinstance(row, dict) and row.get("memory_id") == memory_id
            ):
                return _metadata_content_hash(row)
        if len(rows) < batch_size:
            return None
        offset += batch_size


def _upsert_memory_embedding(repository: object, payload: MemoryEmbeddingPayload) -> bool:
    upsert_embedding = getattr(repository, "upsert_embedding", None)
    if callable(upsert_embedding):
        upsert_embedding(
            memory_id=payload.memory_id,
            namespace=payload.namespace,
            embedding=payload.embedding,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
            dimensions=payload.dimensions,
            content_hash=payload.content_hash,
            metadata={
                **payload.metadata,
            },
        )
        return True

    upsert_memory_embedding = getattr(repository, "upsert_memory_embedding", None)
    if callable(upsert_memory_embedding):
        try:
            upsert_memory_embedding(payload)
        except TypeError:
            upsert_memory_embedding(
                memory_id=payload.memory_id,
                namespace=payload.namespace,
                provider_id=payload.provider_id,
                model_id=payload.model_id,
                dimensions=payload.dimensions,
                content_hash=payload.content_hash,
                embedding=payload.embedding,
                metadata=payload.metadata,
            )
        return True

    return False


def _metadata_content_hash(metadata: object | None) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, dict):
        value = metadata.get("content_hash")
    else:
        value = getattr(metadata, "content_hash", None)
    return str(value) if value is not None else None


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


def should_embed_memory(record: MemoryRecord) -> bool:
    return (
        record.status == MemoryStatus.ACTIVE
        and record.deleted_at is None
        and bool(memory_embedding_text(record))
        and (record.summary != "[forgotten]" or bool(record.content))
    )


def _validate_dimensions(value: int) -> int:
    dimensions = int(value)
    if dimensions <= 0:
        raise MemoryEmbeddingError("embedding dimensions must be positive.")
    return dimensions


def _coerce_embedding(value: object, *, dimensions: int) -> list[float]:
    if not isinstance(value, list):
        raise MemoryEmbeddingError("embedding provider returned a non-list embedding.")
    vector = [float(item) for item in value]
    if len(vector) != dimensions:
        raise MemoryEmbeddingError(
            f"embedding dimensions mismatch: expected {dimensions}, got {len(vector)}."
        )
    return vector


def _deterministic_embedding(text: str, *, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    normalized = " ".join(str(text or "").casefold().split())
    if not normalized:
        return vector
    tokens = normalized.split()
    if not tokens:
        tokens = [normalized]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = -1.0 if digest[4] % 2 else 1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.12g}" for value in vector) + "]"


__all__ = [
    "DeterministicTestEmbeddingProvider",
    "EmbeddingProvider",
    "EmbeddingProviderConfigError",
    "MemoryEmbeddingError",
    "MemoryEmbeddingPayload",
    "MemoryEmbeddingService",
    "OpenAICompatibleEmbeddingProvider",
    "create_memory_embedding_provider",
    "create_memory_embedding_service",
    "memory_embedding_content_hash",
    "memory_embedding_text",
    "should_embed_memory",
    "vector_literal",
]
