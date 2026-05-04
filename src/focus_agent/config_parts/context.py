from __future__ import annotations

from typing import Any, MutableMapping

from .common import _env_bool


def load_context_config(env: MutableMapping[str, str], defaults: Any) -> dict[str, object]:
    return {
        "agent_context_engineering_v2_enabled": _env_bool(
            env,
            "AGENT_CONTEXT_ENGINEERING_V2_ENABLED",
            default=defaults.agent_context_engineering_v2_enabled,
        ),
        "agent_context_artifactize_long_observations": _env_bool(
            env,
            "AGENT_CONTEXT_ARTIFACTIZE_LONG_OBSERVATIONS",
            default=defaults.agent_context_artifactize_long_observations,
        ),
        "agent_context_role_views_enabled": _env_bool(
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
            int(
                env.get(
                    "AGENT_CONTEXT_ARTIFACT_MIN_CHARS",
                    str(defaults.agent_context_artifact_min_chars),
                )
            ),
        ),
        "context_auto_compaction_enabled": _env_bool(
            env,
            "CONTEXT_AUTO_COMPACTION_ENABLED",
            default=defaults.context_auto_compaction_enabled,
        ),
        "context_auto_compaction_pre_send_ratio": float(
            env.get(
                "CONTEXT_AUTO_COMPACTION_PRE_SEND_RATIO",
                str(defaults.context_auto_compaction_pre_send_ratio),
            )
        ),
        "context_auto_compaction_post_turn_ratio": float(
            env.get(
                "CONTEXT_AUTO_COMPACTION_POST_TURN_RATIO",
                str(defaults.context_auto_compaction_post_turn_ratio),
            )
        ),
    }
