from __future__ import annotations

import hashlib
import math
from typing import Protocol

import httpx

from focus_agent.runtime.http_client import shared_sync_http_client


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
        http_client: httpx.Client | None = None,
    ):
        self.model_id = (model or model_id or DEFAULT_OLLAMA_EMBEDDING_MODEL).strip()
        self.dimensions = _validate_dimensions(dimensions)
        self.base_url = _ollama_native_base_url(base_url or DEFAULT_OLLAMA_BASE_URL)
        self.timeout_seconds = float(timeout_seconds)
        self._http_client = http_client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.model_id,
            "input": texts,
        }
        try:
            response = _embedding_http_client(self._http_client).post(
                f"{self.base_url}/api/embed",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout_seconds,
            )
            decoded = _decode_json_response(response)
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
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
        http_client: httpx.Client | None = None,
    ):
        self.model_id = (model or model_id or DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL).strip()
        self.dimensions = _validate_dimensions(dimensions)
        self.api_key = api_key.strip()
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self._http_client = http_client
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
        try:
            response = _embedding_http_client(self._http_client).post(
                f"{self.base_url}/embeddings",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            decoded = _decode_json_response(response)
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
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


def _ollama_native_base_url(base_url: str) -> str:
    normalized = str(base_url or DEFAULT_OLLAMA_BASE_URL).strip().rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[: -len("/v1")].rstrip("/")
    return normalized or DEFAULT_OLLAMA_BASE_URL


def _ollama_model_available(provider: OllamaEmbeddingProvider) -> bool:
    try:
        response = _embedding_http_client(provider._http_client).get(
            f"{provider.base_url}/api/tags",
            timeout=provider.timeout_seconds,
        )
        decoded = _decode_json_response(response)
    except (httpx.HTTPError, TimeoutError, ValueError):
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


def _embedding_http_client(http_client: httpx.Client | None) -> httpx.Client:
    return http_client or shared_sync_http_client()


def _decode_json_response(response: httpx.Response) -> object:
    response.raise_for_status()
    return response.json()


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
    "OllamaEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "ollama_embedding_install_hint",
]
