from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..capabilities.default_tool_modules.workspace import _SKIP_DIR_NAMES, _language_for_path
from .artifacts import artifact_chunks
from .index import RetrievalDocument, RetrievalIndex

WORKSPACE_CHUNKS_COLLECTION = "focus_workspace_chunks"
_DEFAULT_MAX_FILE_BYTES = 512_000


@dataclass(frozen=True, slots=True)
class WorkspaceFile:
    path: Path
    relative_path: str
    size_bytes: int


def iter_indexable_workspace_files(
    *,
    workspace_root: Path,
    path: str | Path = ".",
    max_files: int = 5000,
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> Iterator[WorkspaceFile]:
    root = workspace_root.expanduser().resolve()
    start = _resolve_under_root(root, path)
    count = 0
    if start.is_file():
        candidates = [start]
    else:
        candidates = []
        for current, dirnames, filenames in os.walk(start, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in _SKIP_DIR_NAMES and not (Path(current) / name).is_symlink()
            ]
            candidates.extend(Path(current) / name for name in filenames)
    for file_path in sorted(candidates):
        if count >= max_files or not _is_indexable_file(file_path, max_file_bytes=max_file_bytes):
            continue
        yield WorkspaceFile(
            path=file_path,
            relative_path=file_path.relative_to(root).as_posix(),
            size_bytes=file_path.stat().st_size,
        )
        count += 1


def index_workspace(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    workspace_root: Path,
    path: str | Path = ".",
    max_files: int = 5000,
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> dict[str, int]:
    indexed_files = 0
    indexed_chunks = 0
    skipped_files = 0
    for item in iter_indexable_workspace_files(
        workspace_root=workspace_root,
        path=path,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
    ):
        try:
            content = item.path.read_text(encoding="utf-8", errors="replace")
            indexed_chunks += index_workspace_file(
                retrieval_index=retrieval_index,
                embedding_provider=embedding_provider,
                workspace_root=workspace_root,
                path=item.path,
                content=content,
            )
            indexed_files += 1
        except Exception:  # noqa: BLE001
            skipped_files += 1
    return {
        "indexed_files": indexed_files,
        "indexed_chunks": indexed_chunks,
        "skipped_files": skipped_files,
    }


def index_workspace_file(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    workspace_root: Path,
    path: Path,
    content: str,
) -> int:
    if retrieval_index is None or embedding_provider is None:
        return 0
    root = workspace_root.expanduser().resolve()
    file_path = _resolve_under_root(root, path)
    relative_path = file_path.relative_to(root).as_posix()
    file_hash = hashlib.sha256(content.encode()).hexdigest()
    indexed = 0
    for chunk_index, chunk in enumerate(artifact_chunks(content)):
        retrieval_index.upsert(
            RetrievalDocument(
                collection=WORKSPACE_CHUNKS_COLLECTION,
                doc_id=f"workspace:{hashlib.sha256(relative_path.encode()).hexdigest()}:{chunk_index}",
                source_id=relative_path,
                text=chunk,
                vector=embedding_provider.embed([chunk])[0],
                fields={
                    "source_type": "workspace_file",
                    "path": relative_path,
                    "language": _language_for_path(file_path),
                    "chunk_index": chunk_index,
                    "file_hash": file_hash,
                    "content_hash": hashlib.sha256(chunk.encode()).hexdigest(),
                    "size_bytes": file_path.stat().st_size if file_path.exists() else len(content),
                },
            )
        )
        indexed += 1
    return indexed


class WorkspaceSemanticSearchService:
    def __init__(
        self,
        *,
        retrieval_index: RetrievalIndex | None,
        embedding_provider: Any | None,
        workspace_root: Path,
    ) -> None:
        self.retrieval_index = retrieval_index
        self.embedding_provider = embedding_provider
        self.workspace_root = workspace_root.expanduser().resolve()

    def search_workspace(self, *, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self.retrieval_index is None or self.embedding_provider is None:
            return []
        hits = self.retrieval_index.search(
            collection=WORKSPACE_CHUNKS_COLLECTION,
            query=query,
            vector=self.embedding_provider.embed([query])[0],
            limit=limit,
        )
        results: list[dict[str, Any]] = []
        for hit in hits:
            relative_path = str(hit.fields.get("path") or hit.source_id)
            try:
                file_path = _resolve_under_root(self.workspace_root, relative_path)
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            expected_hash = str(hit.fields.get("file_hash") or "")
            if expected_hash and expected_hash != hashlib.sha256(content.encode()).hexdigest():
                continue
            results.append(
                {
                    "path": relative_path,
                    "chunk_index": hit.fields.get("chunk_index"),
                    "snippet": hit.text[:600],
                    "score": hit.score,
                    "backend": "zvec",
                    "fields": dict(hit.fields),
                }
            )
        return results


def _resolve_under_root(root: Path, path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    resolved.relative_to(root)
    return resolved


def _is_indexable_file(path: Path, *, max_file_bytes: int) -> bool:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_file_bytes:
            return False
        with path.open("rb") as handle:
            return b"\0" not in handle.read(4096)
    except OSError:
        return False
