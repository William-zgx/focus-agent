"""Artifact storage helpers shared by artifact tools and tool-observation persistence."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ...core.context_tool_observation_references import _observation_artifact_id
from ...storage import LocalArtifactStore


class ArtifactBackend:
    def __init__(
        self,
        *,
        artifact_dir: Path,
        artifact_store: Any = None,
        artifact_metadata_repository: Any = None,
        database_uri: str | None = None,
    ) -> None:
        self.artifact_dir = artifact_dir
        self.store = artifact_store or LocalArtifactStore(artifact_dir)
        self._metadata_repository = artifact_metadata_repository
        self._database_uri = database_uri

    def path_for(self, artifact_id: str) -> Path:
        if hasattr(self.store, "path_for"):
            return self.store.path_for(artifact_id)
        return Path(self.store.url(artifact_id)).expanduser().resolve()

    def artifact_id_for_path(self, path: Path) -> str:
        if hasattr(self.store, "artifact_id_for_path"):
            return self.store.artifact_id_for_path(path)
        return path.relative_to(self.artifact_dir.resolve()).as_posix()

    def iter_artifacts(self) -> Iterable[Any]:
        if hasattr(self.store, "iter_artifacts"):
            return self.store.iter_artifacts()
        return LocalArtifactStore(self.artifact_dir).iter_artifacts()

    def metadata_repository(self) -> Any:
        if self._metadata_repository is not None:
            return self._metadata_repository
        if not self._database_uri:
            return None
        from ...repositories.artifact_metadata_repository import ArtifactMetadataRepository

        repository = ArtifactMetadataRepository(self._database_uri)
        repository.setup()
        self._metadata_repository = repository
        return repository

    def upsert_metadata(
        self, *, thread_id: str | None, artifact_id: str, path: Path, title: str
    ) -> None:
        if not thread_id:
            return
        repository = self.metadata_repository()
        if repository is None:
            return
        repository.upsert_from_file(
            thread_id=thread_id,
            artifact_id=artifact_id,
            path=path,
            title=title,
        )

    def save_tool_observation(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        content: str,
        thread_id: str | None,
    ) -> str | None:
        """Persist a trimmed tool's raw output under the trusted runtime thread."""
        if not thread_id:
            raise PermissionError("tool-observation persistence requires a runtime thread scope.")
        artifact_id = _observation_artifact_id(
            thread_id=thread_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
        path = self.path_for(artifact_id)
        self.store.save(artifact_id, content.encode("utf-8"))
        self.upsert_metadata(
            thread_id=thread_id,
            artifact_id=artifact_id,
            path=path,
            title=f"Tool observation: {tool_name}",
        )
        return artifact_id


__all__ = ["ArtifactBackend"]
