from typing import TYPE_CHECKING, Any

from .artifact_metadata_repository import ArtifactMetadataRepository
from .agent_team_repository import AgentTeamRepository, InMemoryAgentTeamRepository
from .branch_repository import BranchRepository
from .memory_repository import MemoryListQuery, MemoryRepository
from .postgres_branch_repository import PostgresBranchRepository
from .postgres_memory_repository import PostgresMemoryRepository
from .postgres_schema import ensure_app_postgres_schema
from .postgres_trajectory_repository import PostgresTrajectoryRepository
from .postgres_user_repository import PostgresUserRepository
from .sqlite_agent_team_repository import SQLiteAgentTeamRepository
from .sqlite_branch_repository import SQLiteBranchRepository
from .sqlite_user_repository import SQLiteUserRepository
from .user_repository import InMemoryUserRepository, UserRepository

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
    "InMemoryUserRepository",
    "MemoryListQuery",
    "MemoryRepository",
    "PostgresAgentTeamRepository",
    "PostgresBranchRepository",
    "PostgresMemoryRepository",
    "PostgresTrajectoryRepository",
    "PostgresUserRepository",
    "SQLiteAgentTeamRepository",
    "SQLiteBranchRepository",
    "SQLiteUserRepository",
    "UserRepository",
    "ensure_app_postgres_schema",
]
