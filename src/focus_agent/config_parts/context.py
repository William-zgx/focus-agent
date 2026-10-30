from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .env import env_bool, env_float, env_int


def load_context_config(env: MutableMapping[str, str], defaults: Any) -> dict[str, object]:
    return {
        "agent_context_engineering_v2_enabled": env_bool(
            env,
            "AGENT_CONTEXT_ENGINEERING_V2_ENABLED",
            default=defaults.agent_context_engineering_v2_enabled,
        ),
        "agent_context_artifactize_long_observations": env_bool(
            env,
            "AGENT_CONTEXT_ARTIFACTIZE_LONG_OBSERVATIONS",
            default=defaults.agent_context_artifactize_long_observations,
        ),
        "agent_context_role_views_enabled": env_bool(
            env,
            "AGENT_CONTEXT_ROLE_VIEWS_ENABLED",
            default=defaults.agent_context_role_views_enabled,
        ),
        "agent_context_tokenizer_mode": (
            "tokenizer_first"
            if str(
                env.get("AGENT_CONTEXT_TOKENIZER_MODE", defaults.agent_context_tokenizer_mode)
            ).lower()
            == "tokenizer_first"
            else "chars_fallback"
        ),
        "agent_context_artifact_min_chars": max(
            1,
            env_int(
                env, "AGENT_CONTEXT_ARTIFACT_MIN_CHARS", defaults.agent_context_artifact_min_chars
            ),
        ),
        "context_auto_compaction_enabled": env_bool(
            env,
            "CONTEXT_AUTO_COMPACTION_ENABLED",
            default=defaults.context_auto_compaction_enabled,
        ),
        "context_auto_compaction_pre_send_ratio": env_float(
            env,
            "CONTEXT_AUTO_COMPACTION_PRE_SEND_RATIO",
            defaults.context_auto_compaction_pre_send_ratio,
        ),
        "context_auto_compaction_post_turn_ratio": env_float(
            env,
            "CONTEXT_AUTO_COMPACTION_POST_TURN_RATIO",
            defaults.context_auto_compaction_post_turn_ratio,
        ),
    }
