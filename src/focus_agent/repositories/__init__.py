from typing import TYPE_CHECKING, Any

from .artifact_metadata_repository import ArtifactMetadataRepository
from .agent_team_repository import AgentTeamRepository, InMemoryAgentTeamRepository
from .branch_repository import BranchRepository
from .postgres_branch_repository import PostgresBranchRepository
from .postgres_schema import ensure_app_postgres_schema
from .postgres_trajectory_repository import PostgresTrajectoryRepository
from .sqlite_agent_team_repository import SQLiteAgentTeamRepository
from .sqlite_branch_repository import SQLiteBranchRepository

if TYPE_CHECKING:
    from .postgres_agent_team_repository import PostgresAgentTeamRepository


def __getattr__(name: str) -> Any:
    if name == "PostgresAgentTeamRepository":
        from .postgres_agent_team_repository import PostgresAgentTeamRepository

        return PostgresAgentTeamRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentTeamRepository",
    "ArtifactMetadataRepository",
    "BranchRepository",
    "InMemoryAgentTeamRepository",
    "PostgresAgentTeamRepository",
    "PostgresBranchRepository",
    "PostgresTrajectoryRepository",
    "SQLiteAgentTeamRepository",
    "SQLiteBranchRepository",
    "ensure_app_postgres_schema",
]
