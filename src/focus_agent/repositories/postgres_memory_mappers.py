from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from psycopg.types.json import Jsonb

from focus_agent.memory.models import MemoryRecord

from .memory_repository import MemoryEmbeddingMetadata


def record_params(record: MemoryRecord, *, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "namespace": list(record.namespace),
        "kind": record.kind.value,
        "scope": record.scope.value,
        "visibility": record.visibility.value,
        "status": record.status.value,
        "embedding_status": record.embedding_status,
        "user_id": record.user_id,
        "root_thread_id": record.root_thread_id,
        "source_thread_id": record.source_thread_id,
        "source_branch_id": record.source_branch_id,
        "semantic_key": record.semantic_key,
        "fingerprint": record.fingerprint,
        "confidence": record.confidence,
        "importance": record.importance,
        "summary": record.summary,
        "content": record.content,
        "promoted_to_main": record.promoted_to_main,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "deleted_at": record.deleted_at,
        "data_json": Jsonb(payload),
    }


def embedding_values(embedding: Sequence[float]) -> list[float]:
    values = [float(value) for value in embedding]
    if not values:
        raise ValueError("embedding must not be empty")
    return values


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.12g}" for value in values) + "]"


def memory_embedding_id(
    *,
    memory_id: str,
    provider_id: str,
    model_id: str,
    content_hash: str,
) -> str:
    seed = json.dumps(
        {
            "memory_id": memory_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "content_hash": content_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"mem-emb:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def embedding_payload_dict(payload: object) -> dict[str, object]:
    if isinstance(payload, dict):
        return dict(payload)
    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="python"))
    if hasattr(payload, "__dataclass_fields__"):
        return {
            field_name: getattr(payload, field_name) for field_name in payload.__dataclass_fields__
        }
    return {
        name: getattr(payload, name)
        for name in dir(payload)
        if not name.startswith("_") and not callable(getattr(payload, name))
    }


def coalesce_text(*values: object) -> str | None:
    for value in values:
        if value is not None:
            text = str(value)
            if text:
                return text
    return None


def coalesce_int(*values: object) -> int | None:
    for value in values:
        if value is not None:
            return int(value)
    return None


def coerce_metadata(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def embedding_extra_metadata(extra: Mapping[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for key in ("kind", "scope", "embedding_text", "text"):
        value = extra.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def embedding_metadata_from_row(row: dict[str, Any]) -> MemoryEmbeddingMetadata:
    return MemoryEmbeddingMetadata(
        embedding_id=str(row["embedding_id"]) if row.get("embedding_id") is not None else None,
        memory_id=str(row["memory_id"]),
        namespace=tuple(row["namespace"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        dimensions=int(row["dimensions"]),
        status=str(row["status"]),
        content_hash=row["content_hash"],
        metadata=decode_json(row["metadata_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def record_from_payload(payload: object) -> MemoryRecord:
    data = decode_json(payload)
    return MemoryRecord.model_validate(data)


def decode_json(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    return dict(value)  # type: ignore[arg-type]
