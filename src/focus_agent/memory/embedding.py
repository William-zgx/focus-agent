from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
import urllib.error
from typing import Any, Protocol
from urllib.request import Request, urlopen

from .embedding_policy import should_embed_memory
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


DEFAULT_OLLAMA_EMBEDDING_MODEL = "embeddinggemma"
DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS = 768
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_DIMENSIONS = 1536


def ollama_embedding_install_hint(model_id: str = DEFAULT_OLLAMA_EMBEDDING_MODEL) -> str:
    return f"ollama pull {model_id or DEFAULT_OLLAMA_EMBEDDING_MODEL}"


class OllamaEmbeddingProvider:
    provider_id = "ollama"

    def __init__(
        self,
        *,
        model: str | None = None,
        model_id: str | None = None,
        dimensions: int = DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.model_id = (model or model_id or DEFAULT_OLLAMA_EMBEDDING_MODEL).strip()
        self.dimensions = _validate_dimensions(dimensions)
        self.base_url = _ollama_native_base_url(base_url or DEFAULT_OLLAMA_BASE_URL)
        self.timeout_seconds = float(timeout_seconds)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.model_id,
            "input": texts,
        }
        request = Request(
            f"{self.base_url}/api/embed",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise MemoryEmbeddingError(
                "Ollama embedding request failed. "
                f"Ensure Ollama is running and install the model with: "
                f"{ollama_embedding_install_hint(self.model_id)}"
            ) from exc

        embeddings = _extract_ollama_embeddings(decoded, expected_count=len(texts))
        return [_coerce_embedding(vector, dimensions=self.dimensions) for vector in embeddings]

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
        self.model_id = (model or model_id or DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL).strip()
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
    model_id = str(getattr(settings, "agent_memory_embedding_model", DEFAULT_OLLAMA_EMBEDDING_MODEL)).strip()
    dimensions = int(getattr(settings, "agent_memory_embedding_dimensions", None) or DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS)
    if provider_id == "deterministic_test":
        return DeterministicTestEmbeddingProvider(model_id=model_id or "deterministic-test", dimensions=dimensions)
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


def _create_auto_memory_embedding_provider(settings: Any) -> EmbeddingProvider | None:
    ollama_provider = _create_ollama_embedding_provider(settings)
    if _ollama_model_available(ollama_provider):
        return ollama_provider

    if not _openai_compatible_fallback_configured(settings):
        raise EmbeddingProviderConfigError(
            "Auto memory embedding provider unavailable. "
            f"Ollama model {ollama_provider.model_id!r} is not installed or Ollama is not running. "
            f"Install it with: {ollama_embedding_install_hint(ollama_provider.model_id)}."
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
            f"Install it with: {ollama_embedding_install_hint(ollama_provider.model_id)}. "
            f"OpenAI-compatible fallback unavailable: {exc}"
        ) from exc


def _create_ollama_embedding_provider(settings: Any) -> OllamaEmbeddingProvider:
    model_id = _ollama_embedding_model(settings)
    return OllamaEmbeddingProvider(
        model_id=model_id,
        dimensions=_ollama_embedding_dimensions(settings, model_id=model_id),
        base_url=_ollama_embedding_base_url(settings),
        timeout_seconds=float(getattr(settings, "agent_memory_embedding_timeout_seconds", 30.0)),
    )


def _create_openai_compatible_embedding_provider(
    settings: Any,
    *,
    model_id: str,
    dimensions: int,
) -> OpenAICompatibleEmbeddingProvider:
    api_key_env = str(getattr(settings, "agent_memory_embedding_api_key_env", "OPENAI_API_KEY") or "").strip()
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


def _ollama_native_base_url(base_url: str) -> str:
    normalized = str(base_url or DEFAULT_OLLAMA_BASE_URL).strip().rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[: -len("/v1")].rstrip("/")
    return normalized or DEFAULT_OLLAMA_BASE_URL


def _ollama_model_available(provider: OllamaEmbeddingProvider) -> bool:
    request = Request(f"{provider.base_url}/api/tags", method="GET")
    try:
        with urlopen(request, timeout=provider.timeout_seconds) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False

    models = decoded.get("models") if isinstance(decoded, dict) else None
    if not isinstance(models, list):
        return False
    expected = provider.model_id
    for item in models:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("model") or "").strip()
        else:
            name = str(item or "").strip()
        if name == expected or name == f"{expected}:latest" or name.split(":", 1)[0] == expected:
            return True
    return False


def _extract_ollama_embeddings(decoded: object, *, expected_count: int) -> list[object]:
    if not isinstance(decoded, dict):
        raise MemoryEmbeddingError("Ollama embedding provider returned an invalid response shape.")
    embeddings = decoded.get("embeddings")
    if embeddings is None and expected_count == 1:
        embedding = decoded.get("embedding")
        embeddings = [embedding] if embedding is not None else None
    if not isinstance(embeddings, list) or len(embeddings) != expected_count:
        raise MemoryEmbeddingError("Ollama embedding provider returned an invalid response shape.")
    return list(embeddings)


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

    list_metadata = getattr(repository, "list_embedding_metadata", None)
    if not callable(list_metadata):
        get_embedding = getattr(repository, "get_memory_embedding", None)
        if callable(get_embedding):
            try:
                return _metadata_content_hash(get_embedding(memory_id=memory_id))
            except TypeError:
                return _metadata_content_hash(get_embedding(memory_id))
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
    "DEFAULT_OLLAMA_BASE_URL",
    "DEFAULT_OLLAMA_EMBEDDING_DIMENSIONS",
    "DEFAULT_OLLAMA_EMBEDDING_MODEL",
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
