from __future__ import annotations

import json
from typing import Any

from langchain.messages import ToolMessage

from .context_token_counting import _estimate_text_tokens
from .context_tool_observation_compaction import (
    _compact_result_list,
    _compact_structured_observation,
    _structured_tool_summary,
    _trim_diff,
    _trim_numbered_content,
)
from .context_tool_observation_json import (
    _collapse_inline,
    _shrink_json_payload,
    _shrink_json_result_list,
    _truncate_json_payload,
    _truncate_text,
)
from .context_tool_observation_references import (
    _artifact_like_ref_from_mapping,
    _collect_artifact_like_refs,
    _format_textual_tool_reference,
    _structured_tool_reference,
    _tool_observation_ref,
)
from .types import ContextBudget


def _tool_observation_char_limit(budget: ContextBudget) -> int:
    return max(
        1,
        int(budget.tool_observation_token_limit) * max(1, int(budget.chars_per_token)),
    )


def _tool_reference_char_limit(budget: ContextBudget) -> int:
    return max(
        1,
        int(budget.tool_reference_token_limit) * max(1, int(budget.chars_per_token)),
    )


def _tool_observation_budget_mode(budget: ContextBudget) -> str:
    if budget.tool_observation_budget_mode == "inherit":
        return budget.token_budget_mode
    return budget.tool_observation_budget_mode


def _tool_observation_tokenizer_id(budget: ContextBudget) -> str | None:
    return budget.tool_observation_tokenizer_id or budget.tokenizer_id


def _tool_observation_budget_units(text: str, *, budget: ContextBudget) -> int:
    return _estimate_text_tokens(
        text,
        chars_per_token=budget.chars_per_token,
        tokenizer_id=_tool_observation_tokenizer_id(budget),
        tokenizer_first=_tool_observation_budget_mode(budget) == "tokenizer_first",
    )


def _tool_observation_within_budget(
    text: str,
    *,
    budget: ContextBudget,
    max_chars: int,
    enforce_token_budget: bool,
) -> bool:
    if len(text) > max_chars:
        return False
    if not enforce_token_budget:
        return True
    return (
        _tool_observation_budget_units(text, budget=budget)
        <= budget.tool_observation_token_limit
    )


def trim_tool_observation(
    observation: Any,
    *,
    tool_name: str = "",
    tool_call_id: str = "",
    budget: ContextBudget | None = None,
    max_chars: int | None = None,
    artifactize_for_prompt: bool = False,
    force_artifactize: bool = False,
) -> str:
    text = str(observation)
    effective_budget = budget or ContextBudget()
    limit = max_chars if max_chars is not None else _tool_observation_char_limit(effective_budget)
    limit = max(1, int(limit))
    enforce_token_budget = max_chars is None
    if _tool_observation_within_budget(
        text,
        budget=effective_budget,
        max_chars=limit,
        enforce_token_budget=enforce_token_budget,
    ) and not (artifactize_for_prompt and force_artifactize):
        return text

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        if (
            not artifactize_for_prompt
            and budget is None
            and max_chars is not None
            and not tool_name
        ):
            return _truncate_text(text, max_chars=limit)
        rendered = _format_textual_tool_reference(
            text,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            max_chars=limit,
            reference_chars=min(limit, _tool_reference_char_limit(effective_budget)),
        )
        if artifactize_for_prompt:
            textual_payload = json.loads(rendered)
            textual_payload["truncated_by_context_policy"] = True
            rendered = _truncate_json_payload(textual_payload, max_chars=limit)
        if not enforce_token_budget:
            return rendered
        return _fit_tool_observation_to_budget(
            rendered,
            payload=json.loads(rendered),
            budget=effective_budget,
            max_chars=limit,
        )

    compact = _compact_structured_observation(
        payload,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        max_chars=limit,
        reference_chars=min(limit, _tool_reference_char_limit(effective_budget)),
        artifactize_for_prompt=artifactize_for_prompt,
    )
    rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if _tool_observation_within_budget(
        rendered,
        budget=effective_budget,
        max_chars=limit,
        enforce_token_budget=enforce_token_budget,
    ):
        return rendered
    return _fit_tool_observation_to_budget(
        rendered,
        payload=compact,
        budget=effective_budget,
        max_chars=limit,
    )


def _tool_name_for_tool_message(message: ToolMessage) -> str:
    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, dict):
        return ""
    tool_name = artifact.get("tool_name")
    if isinstance(tool_name, str):
        return tool_name
    tool_payload = artifact.get("tool")
    if isinstance(tool_payload, dict) and isinstance(tool_payload.get("name"), str):
        return str(tool_payload["name"])
    return ""


def _tool_message_was_runtime_compacted(message: ToolMessage, *, max_chars: int) -> bool:
    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, dict):
        return False
    runtime = artifact.get("runtime")
    if not isinstance(runtime, dict):
        return False
    if bool(runtime.get("observation_prompt_compacted")):
        return True
    original_chars = runtime.get("observation_original_chars")
    if isinstance(original_chars, int):
        return original_chars > max_chars
    return False


def _prompt_observation_for_tool_message(message: ToolMessage) -> str:
    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, dict):
        return ""
    value = artifact.get("prompt_observation")
    return str(value) if isinstance(value, str) else ""


def _fit_tool_observation_to_budget(
    text: str,
    *,
    budget: ContextBudget,
    max_chars: int,
    payload: Any | None = None,
) -> str:
    candidate_payload = payload
    if candidate_payload is None:
        try:
            candidate_payload = json.loads(text)
        except json.JSONDecodeError:
            candidate_payload = None

    def _render(limit: int) -> str:
        if isinstance(candidate_payload, (dict, list)):
            return _truncate_json_payload(candidate_payload, max_chars=limit)
        return _truncate_text(text, max_chars=limit)

    candidate = _render(max_chars)
    if _tool_observation_within_budget(
        candidate,
        budget=budget,
        max_chars=max_chars,
        enforce_token_budget=True,
    ):
        return candidate

    low = 2 if isinstance(candidate_payload, (dict, list)) else 1
    high = min(len(candidate), max_chars)
    best = candidate
    while low <= high:
        mid = (low + high) // 2
        probe = _render(mid)
        if _tool_observation_within_budget(
            probe,
            budget=budget,
            max_chars=max_chars,
            enforce_token_budget=True,
        ):
            best = probe
            low = mid + 1
        else:
            high = mid - 1
    return best


__all__ = [
    "_artifact_like_ref_from_mapping",
    "_collapse_inline",
    "_collect_artifact_like_refs",
    "_compact_result_list",
    "_compact_structured_observation",
    "_fit_tool_observation_to_budget",
    "_format_textual_tool_reference",
    "_prompt_observation_for_tool_message",
    "_shrink_json_payload",
    "_shrink_json_result_list",
    "_structured_tool_reference",
    "_structured_tool_summary",
    "_tool_message_was_runtime_compacted",
    "_tool_name_for_tool_message",
    "_tool_observation_budget_mode",
    "_tool_observation_budget_units",
    "_tool_observation_char_limit",
    "_tool_observation_ref",
    "_tool_observation_tokenizer_id",
    "_tool_observation_within_budget",
    "_tool_reference_char_limit",
    "_trim_diff",
    "_trim_numbered_content",
    "_truncate_json_payload",
    "_truncate_text",
    "trim_tool_observation",
]
