from __future__ import annotations

from dataclasses import dataclass

from ..branch_decision import BranchDecisionService
from ..capabilities import ToolRegistry
from ..memory import MemoryExtractor, MemoryPolicy, MemoryRetriever, MemoryWriter
from ..memory.embedding import MemoryEmbeddingService
from ..repositories.branch_repository import BranchRepository
from ..repositories.productivity_repository import ProductivityRepository
from ..repositories.user_repository import UserRepository
from ..services.agent_team import AgentTeamService
from ..services.branches import BranchService
from ..services.productivity import ProductivityService
from ..services.users import UserService
from ..skills import SkillRegistry
from ..storage.postgres import PostgresConnectionProvider


@dataclass(slots=True)
class RuntimePersistence:
    checkpointer: object
    store: object
    repo: BranchRepository
    user_repository: UserRepository
    memory_repository: object | None
    productivity_repository: ProductivityRepository
    trajectory_recorder: object | None
    artifact_metadata_repository: object | None
    run_journal: object
    postgres_connection_provider: PostgresConnectionProvider | None = None
    pool: PostgresConnectionProvider | None = None


@dataclass(slots=True)
class RuntimeMemoryComponents:
    memory_policy: MemoryPolicy
    memory_retriever: MemoryRetriever
    memory_writer: MemoryWriter
    memory_extractor: MemoryExtractor
    memory_repository: object | None
    memory_embedding_service: MemoryEmbeddingService | None
    memory_embedding_provider: object | None
    memory_embedding_backend_error: str | None = None


@dataclass(slots=True)
class RuntimeMemoryEmbeddingSetup:
    provider: object | None
    backend_error: str | None
    dimensions: int
    memory_embeddings_enabled: bool


@dataclass(slots=True)
class RuntimeRegistries:
    skill_registry: SkillRegistry
    tool_registry: ToolRegistry


@dataclass(slots=True)
class RuntimeServices:
    branch_service: BranchService
    agent_team_service: AgentTeamService
    branch_decision_service: BranchDecisionService
    user_service: UserService
    productivity_service: ProductivityService
