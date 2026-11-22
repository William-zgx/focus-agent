from __future__ import annotations

from ..core.repo_call import has_repo_method


class MemoryEmbeddingCleanupError(RuntimeError):
    pass


def delete_embedding_artifacts(
    repository: object,
    memory_id: str,
    *,
    retrieval_index: object | None = None,
) -> None:
    errors: list[Exception] = []
    try:
        if has_repo_method(repository, "delete_embedding"):
            repository.delete_embedding(memory_id)
        elif has_repo_method(repository, "delete_memory_embedding"):
            repository.delete_memory_embedding(memory_id)
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)
    if retrieval_index is not None:
        try:
            retrieval_index.delete(collection="focus_memory", doc_id=f"memory:{memory_id}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    if errors:
        raise MemoryEmbeddingCleanupError(
            f"failed to delete embedding artifacts for {memory_id}: {errors}"
        )


__all__ = ["MemoryEmbeddingCleanupError", "delete_embedding_artifacts"]
