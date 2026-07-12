"""Refactored graph execution components with lazy compatibility exports."""

from importlib import import_module
from typing import Any

_MODULE_EXPORTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        ".agent_loop",
        ("make_agent_loop_node",),
    ),
    (
        ".builder",
        (
            "TurnToolExposure",
            "_canonicalize_tool_call_args",
            "_classify_turn_tool_exposure",
            "_classify_turn_tool_policy",
            "_count_tool_call_rounds_since_latest_human",
            "_ensure_reasoning_content_for_tool_call_history",
            "_fallback_answer_from_tool_results",
            "_format_plan_block",
            "build_tool_intent_plan",
            "_live_web_research_should_start_with_search",
            "_looks_like_textual_tool_call_artifact",
            "_messages_for_model",
            "_parse_plan_json",
            "_parse_reflection_json",
            "_repair_and_dedupe_tool_calls",
            "_repair_tool_free_answer_response",
            "_should_force_tool_free_answer",
            "_should_plan",
            "_tool_policy_note",
            "_tools_for_policy",
            "build_graph",
        ),
    ),
    (
        ".policy",
        (
            "_BRANCH_ACTION_GUARD_NOTE",
            "_DIRECT_ANSWER_NOTE",
            "_LIVE_WEB_TOOL_NOTE",
            "_WORKSPACE_TOOL_NOTE",
            "TurnToolExposure",
            "build_tool_intent_plan",
            "_classify_turn_tool_exposure",
            "_classify_turn_tool_policy",
            "_live_web_research_should_start_with_search",
            "_temporal_live_web_search_args",
            "_tool_intent_plan_requires_temporal_anchor",
            "_tool_policy_note",
            "_tools_for_policy",
            "_workspace_lookup_should_start_with_search",
            "_workspace_search_query",
        ),
    ),
    (
        ".policy_intent",
        (
            "first_mapping_text",
            "is_tool_carryover_confirmation",
            "normalize_carryover_text",
            "pending_live_web_search_intent",
            "requires_temporal_anchor",
        ),
    ),
    (
        ".tool_execution",
        (
            "HarnessToolServices",
            "_apply_result_hooks",
            "_patch_tool_message_content",
            "_patch_tool_message_error",
            "make_tool_executor_node",
        ),
    ),
    (
        ".tool_repair",
        (
            "_MAX_CONSECUTIVE_TOOL_CALL_ROUNDS",
            "_TOOL_EXHAUSTION_NOTE",
            "_TOOL_CALL_PROTOCOL_REPAIR_NOTE",
            "_TOOL_CALL_MARKUP_REPAIR_NOTE",
            "_TOOL_CALL_LAST_RESORT_NOTE",
            "_TOOL_CALL_REPAIR_FALLBACK_TEXT",
            "_TOOL_RESULT_SYNTHESIS_NOTE",
            "_REASONING_MESSAGE_BLOCK_TYPES",
            "_TOOL_MESSAGE_BLOCK_TYPES",
            "_has_tool_calls",
            "_find_trailing_tool_span_start",
            "_collapse_unanswered_trailing_humans",
            "_messages_for_model",
            "_count_tool_call_rounds_since_latest_human",
            "_should_force_tool_free_answer",
            "_message_text",
            "_stringify_message_block",
            "_sanitize_assistant_tool_call_message",
            "_thinking_mode_requires_reasoning_content",
            "_ensure_reasoning_content_for_tool_call_history",
            "_known_tool_names",
            "_canonicalize_tool_call_args",
            "_tool_call_signature",
            "_repair_and_dedupe_tool_calls",
            "_looks_like_textual_tool_call_artifact",
            "_latest_human_message_text",
            "_latest_final_ai_text",
            "_context_budget_from_state",
            "_truncate_inline",
            "_latest_turn_messages",
            "_fallback_answer_from_tool_results",
            "_tool_call_args_summary",
            "_tool_runtime_summary",
            "_tool_observation_summary",
            "_tool_result_snippets",
            "_tool_result_synthesis_prompt",
            "_has_tool_result_messages",
            "_tool_result_fallback_message",
            "_invoke_tool_result_synthesis",
            "_invoke_with_tool_result_fallback",
            "_repair_textual_tool_call_response",
            "_repair_tool_free_answer_response",
        ),
    ),
)

_EXPORT_MODULES: dict[str, str] = {}
__all__: list[str] = []
for _module_name, _module_exports in _MODULE_EXPORTS:
    for _export_name in _module_exports:
        if _export_name not in _EXPORT_MODULES:
            __all__.append(_export_name)
        _EXPORT_MODULES[_export_name] = _module_name

_LAZY_SUBMODULES = frozenset(module_name.removeprefix(".") for module_name, _ in _MODULE_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is not None:
        value = getattr(import_module(module_name, __name__), name)
        globals()[name] = value
        return value
    if name in _LAZY_SUBMODULES:
        value = import_module(f".{name}", __name__)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__, *_LAZY_SUBMODULES})
