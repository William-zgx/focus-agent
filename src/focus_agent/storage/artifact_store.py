from __future__ import annotations

from typing import Protocol


class ArtifactStore(Protocol):
    def save(self, artifact_id: str, content: bytes) -> str: ...

    def load(self, artifact_id: str) -> bytes: ...

    def exists(self, artifact_id: str) -> bool: ...

    def url(self, artifact_id: str) -> str: ...


__all__ = ["ArtifactStore"]
