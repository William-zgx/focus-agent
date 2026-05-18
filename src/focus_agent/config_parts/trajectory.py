from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .common import _coerce_bool, _env_bool


def load_trajectory_config(
    env: MutableMapping[str, str],
    defaults: Any,
    *,
    database_uri: str | None,
) -> dict[str, object]:
    trajectory_enabled = _coerce_bool(env.get("TRAJECTORY_ENABLED"))
    return {
        "trajectory_enabled": bool(database_uri)
        if trajectory_enabled is None
        else trajectory_enabled,
        "trajectory_observation_max_chars": int(
            env.get(
                "TRAJECTORY_OBSERVATION_MAX_CHARS",
                str(defaults.trajectory_observation_max_chars),
            )
        ),
        "trajectory_answer_max_chars": int(
            env.get(
                "TRAJECTORY_ANSWER_MAX_CHARS",
                str(defaults.trajectory_answer_max_chars),
            )
        ),
        "trajectory_hash_user_id": _env_bool(
            env, "TRAJECTORY_HASH_USER_ID", default=defaults.trajectory_hash_user_id
        ),
    }
