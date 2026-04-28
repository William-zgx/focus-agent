"""Compatibility imports for API route helpers.

Routers should import narrower helpers from ``focus_agent.api.route_utils`` directly.
This module keeps explicit compatibility exports for tests and legacy imports.
"""

from __future__ import annotations

from focus_agent.observability.trajectory_actions import (
    build_promoted_dataset_payload,
    load_turn_export,
    run_replay_for_turn,
)

from .route_utils.lifespan import app_lifespan
from .route_utils.token_usage import (
    _aggregate_token_usage_from_turns,
    _annotate_branch_tree_token_usage,
)

__all__ = [
    "_aggregate_token_usage_from_turns",
    "_annotate_branch_tree_token_usage",
    "app_lifespan",
    "build_promoted_dataset_payload",
    "load_turn_export",
    "run_replay_for_turn",
]
