from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .memory.embedding import (
    MemoryEmbeddingError,
    MemoryEmbeddingService,
    create_memory_embedding_provider,
)
from .repositories.memory_repository import MemoryListQuery
from .repositories.postgres_memory_repository import PostgresMemoryRepository


@dataclass(frozen=True, slots=True)
class _ResolvedEmbedding:
    provider: object | None
    error: str | None
    dimensions: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="focus-agent-memory-embedding",
        description="Inspect and rebuild the canonical Postgres memory embedding index.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--database-uri",
        help="PostgreSQL connection string. Defaults to DATABASE_URI from settings/env.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "doctor",
        help="Print a read-only JSON health summary for memory embeddings.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    rebuild = subparsers.add_parser(
        "rebuild",
        help="Drop and recreate only focus_memory_embeddings and its indexes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    rebuild.add_argument(
        "--confirm-delete-index",
        action="store_true",
        help="Required safety flag. Canonical focus_memories records are not deleted.",
    )
    rebuild.add_argument(
        "--backfill",
        action="store_true",
        help="Backfill active canonical memories after recreating the embedding index.",
    )
    rebuild.add_argument(
        "--limit",
        type=_positive_int,
        default=1000,
        help="Maximum active memories to backfill when --backfill is set.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    database_uri = str(args.database_uri or settings.database_uri or "").strip()
    resolved = _resolve_embedding(settings)

    if args.command == "doctor":
        summary = _doctor_summary(
            settings=settings,
            database_uri=database_uri,
            resolved=resolved,
        )
        _print_json(summary)
        return 0 if bool(summary.get("ready")) else 1

    if args.command == "rebuild":
        if not args.confirm_delete_index:
            _print_json(
                {
                    "ready": False,
                    "status": "refused",
                    "reason": "--confirm-delete-index is required",
                },
                file=sys.stderr,
            )
            return 2
        if not database_uri:
            _print_json(
                {
                    "ready": False,
                    "status": "refused",
                    "reason": "DATABASE_URI is required",
                },
                file=sys.stderr,
            )
            return 2
        summary = _rebuild_summary(
            settings=settings,
            database_uri=database_uri,
            resolved=resolved,
            backfill=bool(args.backfill),
            limit=int(args.limit),
        )
        _print_json(summary)
        return 0 if bool(summary.get("ready")) else 1

    parser.error(f"unknown command: {args.command}")
    return 2


def _resolve_embedding(settings: Settings) -> _ResolvedEmbedding:
    provider: object | None = None
    error: str | None = None
    try:
        provider = create_memory_embedding_provider(settings)
    except MemoryEmbeddingError as exc:
        error = str(exc)
    return _ResolvedEmbedding(
        provider=provider,
        error=error,
        dimensions=_embedding_dimensions(settings=settings, provider=provider),
    )


def _embedding_dimensions(*, settings: Settings, provider: object | None) -> int:
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


def _doctor_summary(
    *,
    settings: Settings,
    database_uri: str,
    resolved: _ResolvedEmbedding,
) -> dict[str, object]:
    provider_summary = _provider_summary(settings=settings, resolved=resolved)
    repository_summary: dict[str, object] = {
        "checked": False,
        "ready": False,
        "reason": "DATABASE_URI is not set",
    }
    if database_uri:
        repository_summary = _repository_summary(
            settings=settings,
            database_uri=database_uri,
            dimensions=resolved.dimensions,
        )
    provider_ready = bool(provider_summary.get("ready"))
    repository_ready = bool(repository_summary.get("ready"))
    return {
        "ready": provider_ready and repository_ready,
        "status": "ready" if provider_ready and repository_ready else "degraded",
        "settings": _settings_summary(settings, database_uri=database_uri),
        "provider": provider_summary,
        "repository": repository_summary,
    }


def _rebuild_summary(
    *,
    settings: Settings,
    database_uri: str,
    resolved: _ResolvedEmbedding,
    backfill: bool,
    limit: int,
) -> dict[str, object]:
    repository = PostgresMemoryRepository(database_uri)
    status = repository.rebuild_embedding_index(
        dimensions=resolved.dimensions,
        vector_index=bool(getattr(settings, "agent_memory_vector_index_enabled", False)),
        pgvector_extension_mode=str(
            getattr(settings, "agent_memory_pgvector_extension_mode", "auto_create")
            or "auto_create"
        ),
    )
    backfill_summary = _backfill_summary(
        repository=repository,
        resolved=resolved,
        settings=settings,
        enabled=backfill,
        limit=limit,
    )
    ready = bool(status.get("extension_installed")) and bool(status.get("dimensions_match"))
    return {
        "ready": ready,
        "status": "ready" if ready else "degraded",
        "rebuild": status,
        "provider": _provider_summary(settings=settings, resolved=resolved),
        "backfill": backfill_summary,
    }


def _settings_summary(settings: Settings, *, database_uri: str) -> dict[str, object]:
    return {
        "database_uri_present": bool(database_uri),
        "embedding_enabled": bool(getattr(settings, "agent_memory_embedding_enabled", False)),
        "backend": str(getattr(settings, "agent_memory_embedding_backend", "") or ""),
        "provider": str(getattr(settings, "agent_memory_embedding_provider", "") or ""),
        "model": str(getattr(settings, "agent_memory_embedding_model", "") or ""),
        "dimensions": int(getattr(settings, "agent_memory_embedding_dimensions", 1536) or 1536),
        "vector_search_mode": str(getattr(settings, "agent_memory_vector_search_mode", "") or ""),
        "vector_index_enabled": bool(getattr(settings, "agent_memory_vector_index_enabled", False)),
        "pgvector_extension_mode": str(
            getattr(settings, "agent_memory_pgvector_extension_mode", "auto_create")
            or "auto_create"
        ),
    }


def _provider_summary(*, settings: Settings, resolved: _ResolvedEmbedding) -> dict[str, object]:
    provider = resolved.provider
    if provider is None:
        summary: dict[str, object] = {
            "ready": False,
            "error": resolved.error or "disabled",
            "dimensions": resolved.dimensions,
        }
        install_hint = _ollama_install_hint(settings)
        if install_hint:
            summary["install_hint"] = install_hint
        return summary
    return {
        "ready": True,
        "provider_id": str(getattr(provider, "provider_id", "unknown")),
        "model_id": str(getattr(provider, "model_id", "unknown")),
        "dimensions": int(getattr(provider, "dimensions", resolved.dimensions)),
    }


def _repository_summary(
    *,
    settings: Settings,
    database_uri: str,
    dimensions: int,
) -> dict[str, object]:
    repository = PostgresMemoryRepository(database_uri)
    try:
        status = repository.inspect_pgvector_support(
            dimensions=dimensions,
            vector_index=bool(getattr(settings, "agent_memory_vector_index_enabled", False)),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "checked": True,
            "ready": False,
            "error": f"inspection_failed: {type(exc).__name__}",
        }
    ready = (
        bool(status.get("extension_installed"))
        and bool(status.get("embeddings_table_exists"))
        and bool(status.get("dimensions_match"))
    )
    if bool(getattr(settings, "agent_memory_vector_index_enabled", False)):
        ready = ready and bool(status.get("vector_index_exists"))
    return {"checked": True, "ready": ready, **status}


def _backfill_summary(
    *,
    repository: PostgresMemoryRepository,
    resolved: _ResolvedEmbedding,
    settings: Settings,
    enabled: bool,
    limit: int,
) -> dict[str, object]:
    if not enabled:
        return {"status": "skipped", "reason": "--backfill was not provided"}
    if resolved.provider is None:
        return {
            "status": "skipped",
            "reason": resolved.error or "memory embedding provider unavailable",
        }
    service = MemoryEmbeddingService(
        repository=repository,
        provider=resolved.provider,
        batch_size=int(getattr(settings, "agent_memory_embedding_batch_size", 32)),
    )
    records = repository.list_records(MemoryListQuery(status="active", limit=limit))
    result = service.embed_records(list(records))
    return {"status": "completed", "scanned": len(records), **result}


def _ollama_install_hint(settings: Settings) -> str | None:
    backend = str(getattr(settings, "agent_memory_embedding_backend", "") or "").strip().lower()
    provider = str(getattr(settings, "agent_memory_embedding_provider", "") or "").strip().lower()
    model = str(getattr(settings, "agent_memory_embedding_model", "") or "").strip().lower()
    if (
        backend in {"auto", "ollama"}
        or provider == "ollama"
        or model in {"embeddinggemma", "embedding-gemma"}
    ):
        return "ollama pull embeddinggemma"
    return None


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def _print_json(payload: dict[str, object], *, file: Any | None = None) -> None:
    if file is None:
        file = sys.stdout
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), file=file)


if __name__ == "__main__":
    raise SystemExit(main())
