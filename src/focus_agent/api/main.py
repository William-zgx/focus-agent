from __future__ import annotations

from fastapi import FastAPI

from focus_agent.config import Settings
from focus_agent.observability.trajectory_actions import (
    build_promoted_dataset_payload,
    load_turn_export,
    run_replay_for_turn,
)

from .errors import register_exception_handlers
from .middleware import configure_middleware
from .route_utils.lifespan import app_lifespan
from .route_utils.token_usage import (
    _aggregate_token_usage_from_turns,
    _annotate_branch_tree_token_usage,
)
from .routers import (
    admin_users,
    agent_governance,
    agent_team,
    auth_models,
    branches_merge,
    conversation_chat_context,
    harness_runs,
    health_metrics,
    memory,
    observability,
    productivity,
)
from .routers.frontend_static import register_frontend_routes


def create_app() -> FastAPI:
    settings = Settings.from_env()
    app = FastAPI(
        title='focus-agent',
        version=settings.app_version,
        description='Long-dialogue research agent API with branchable conversations.',
        lifespan=app_lifespan,
    )

    configure_middleware(app, settings=settings)
    register_exception_handlers(app)

    app.include_router(health_metrics.router)
    app.include_router(harness_runs.router)
    register_frontend_routes(app, settings=settings)
    app.include_router(auth_models.router)
    app.include_router(admin_users.router)
    app.include_router(agent_team.router)
    app.include_router(agent_governance.router)
    app.include_router(memory.router)
    app.include_router(productivity.router)
    app.include_router(observability.router)
    app.include_router(conversation_chat_context.router)
    app.include_router(branches_merge.router)
    return app


app = create_app()


__all__ = [
    "app",
    "_aggregate_token_usage_from_turns",
    "_annotate_branch_tree_token_usage",
    "app_lifespan",
    "build_promoted_dataset_payload",
    "create_app",
    "load_turn_export",
    "run_replay_for_turn",
]
