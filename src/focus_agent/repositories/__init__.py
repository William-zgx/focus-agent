from typing import TYPE_CHECKING, Any

from .agent_team_repository import AgentTeamRepository, InMemoryAgentTeamRepository
from .branch_repository import BranchRepository
from .memory_repository import MemoryListQuery, MemoryRepository
from .user_repository import InMemoryUserRepository, UserRepository

if TYPE_CHECKING:
    from .artifact_metadata_repository import ArtifactMetadataRepository
    from .postgres_agent_team_repository import PostgresAgentTeamRepository
    from .postgres_branch_repository import PostgresBranchRepository
    from .postgres_memory_repository import PostgresMemoryRepository
    from .postgres_schema import ensure_app_postgres_schema
    from .postgres_trajectory_repository import PostgresTrajectoryRepository
    from .postgres_user_repository import PostgresUserRepository
    from .sqlite_agent_team_repository import SQLiteAgentTeamRepository
    from .sqlite_branch_repository import SQLiteBranchRepository
    from .sqlite_user_repository import SQLiteUserRepository


def __getattr__(name: str) -> Any:
    if name == "PostgresAgentTeamRepository":
        from .postgres_agent_team_repository import PostgresAgentTeamRepository

        return PostgresAgentTeamRepository
    if name == "ArtifactMetadataRepository":
        from .artifact_metadata_repository import ArtifactMetadataRepository

        return ArtifactMetadataRepository
    if name == "PostgresBranchRepository":
        from .postgres_branch_repository import PostgresBranchRepository

        return PostgresBranchRepository
    if name == "PostgresMemoryRepository":
        from .postgres_memory_repository import PostgresMemoryRepository

        return PostgresMemoryRepository
    if name == "PostgresTrajectoryRepository":
        from .postgres_trajectory_repository import PostgresTrajectoryRepository

        return PostgresTrajectoryRepository
    if name == "PostgresUserRepository":
        from .postgres_user_repository import PostgresUserRepository

        return PostgresUserRepository
    if name == "SQLiteAgentTeamRepository":
        from .sqlite_agent_team_repository import SQLiteAgentTeamRepository

        return SQLiteAgentTeamRepository
    if name == "SQLiteBranchRepository":
        from .sqlite_branch_repository import SQLiteBranchRepository

        return SQLiteBranchRepository
    if name == "SQLiteUserRepository":
        from .sqlite_user_repository import SQLiteUserRepository

        return SQLiteUserRepository
    if name == "ensure_app_postgres_schema":
        from .postgres_schema import ensure_app_postgres_schema

        return ensure_app_postgres_schema
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
