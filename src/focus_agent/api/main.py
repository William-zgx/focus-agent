from __future__ import annotations

from fastapi import FastAPI

from focus_agent.config import Settings

from .errors import register_exception_handlers
from .middleware import configure_middleware
from .route_helpers import (
    _aggregate_token_usage_from_turns,
    _annotate_branch_tree_token_usage,
    app_lifespan,
    build_promoted_dataset_payload,
    load_turn_export,
    run_replay_for_turn,
)
from .routers import (
    agent_governance,
    agent_team,
    auth_models,
    branches_merge,
    conversation_chat_context,
    health_metrics,
    observability,
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
    register_frontend_routes(app, settings=settings)
    app.include_router(auth_models.router)
    app.include_router(agent_team.router)
    app.include_router(agent_governance.router)
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
