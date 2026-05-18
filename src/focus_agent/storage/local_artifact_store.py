from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LocalArtifactInfo:
    artifact_id: str
    path: Path
    size_bytes: int
    updated_at: datetime


class LocalArtifactStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, artifact_id: str) -> Path:
        if not artifact_id.strip():
            raise ValueError("artifact_id must not be empty.")
        candidate = Path(artifact_id).expanduser()
        path = candidate.resolve() if candidate.is_absolute() else (self.root / candidate).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"Artifact path must stay within artifact directory: {self.root}"
            ) from exc
        return path

    def artifact_id_for_path(self, path: Path | str) -> str:
        return Path(path).expanduser().resolve().relative_to(self.root).as_posix()

    def save(self, artifact_id: str, content: bytes) -> str:
        path = self.path_for(artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return self.url(artifact_id)

    def load(self, artifact_id: str) -> bytes:
        return self.path_for(artifact_id).read_bytes()

    def exists(self, artifact_id: str) -> bool:
        path = self.path_for(artifact_id)
        return path.exists() and path.is_file()

    def url(self, artifact_id: str) -> str:
        return str(self.path_for(artifact_id))

    def iter_artifacts(self) -> Iterator[LocalArtifactInfo]:
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            yield LocalArtifactInfo(
                artifact_id=path.relative_to(self.root).as_posix(),
                path=path,
                size_bytes=stat.st_size,
                updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
            )


__all__ = ["LocalArtifactInfo", "LocalArtifactStore"]
