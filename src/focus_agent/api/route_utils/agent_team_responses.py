from __future__ import annotations

from inspect import Parameter, signature
from typing import Any

from fastapi import Response

from focus_agent.core.repo_call import has_repo_method

from ..contracts import AgentTeamSessionViewResponse

_DEPRECATED_ROUTE_LINK_REL = "successor-version"


def _mark_deprecated_route(response: Response, *, canonical_path: str) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = f'<{canonical_path}>; rel="{_DEPRECATED_ROUTE_LINK_REL}"'
    response.headers["X-Focus-Agent-Canonical-Path"] = canonical_path


def _model_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if has_repo_method(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _planning_metadata_payload(
    payload: dict[str, Any],
    *,
    default_source: str | None = None,
) -> dict[str, Any]:
    session = _model_payload(payload.get("session"))
    tasks = [_model_payload(task) for task in payload.get("tasks") or payload.get("items") or []]
    planning = payload.get("planning")
    if not isinstance(planning, dict):
        planning = session.get("planning") if isinstance(session.get("planning"), dict) else {}
    metadata: dict[str, Any] = {
        "source": planning.get("source") or session.get("planning_source") or default_source,
        "rationale": planning.get("rationale") or session.get("planning_rationale"),
        "planner_model_id": planning.get("planner_model_id") or session.get("planner_model_id"),
        "generated_at": planning.get("generated_at") or session.get("plan_generated_at"),
        "plan_hash": planning.get("plan_hash") or session.get("plan_hash"),
        "error": planning.get("error") or session.get("planning_error"),
        "task_count": planning.get("task_count") if planning.get("task_count") is not None else len(tasks),
    }
    for task in tasks:
        if metadata["source"] is None:
            metadata["source"] = task.get("plan_source")
        if metadata["rationale"] is None:
            metadata["rationale"] = task.get("planning_rationale")
        for ref in task.get("context_refs") or []:
            if not isinstance(ref, dict):
                continue
            if metadata["source"] is None:
                metadata["source"] = ref.get("plan_source") or ref.get("source")
            if metadata["rationale"] is None:
                metadata["rationale"] = ref.get("planning_rationale") or ref.get("rationale")
            if metadata["planner_model_id"] is None:
                metadata["planner_model_id"] = ref.get("planner_model_id") or ref.get("model_id")
            if metadata["generated_at"] is None:
                metadata["generated_at"] = ref.get("generated_at")
            if metadata["plan_hash"] is None:
                metadata["plan_hash"] = ref.get("plan_hash")
            if metadata["error"] is None:
                metadata["error"] = ref.get("error")
    return metadata


def _call_plan_session(service: Any, **kwargs: Any) -> tuple[Any, list[Any]]:
    plan_session = service.plan_session
    params = signature(plan_session).parameters
    if any(param.kind == Parameter.VAR_KEYWORD for param in params.values()):
        return plan_session(**kwargs)
    return plan_session(**{key: value for key, value in kwargs.items() if key in params})


def _view_response(payload: dict[str, Any]) -> AgentTeamSessionViewResponse:
    data = dict(payload)
    data["planning"] = _planning_metadata_payload(data)
    return AgentTeamSessionViewResponse.model_validate(data)


__all__ = [
    "_DEPRECATED_ROUTE_LINK_REL",
    "_call_plan_session",
    "_mark_deprecated_route",
    "_model_payload",
    "_planning_metadata_payload",
    "_view_response",
]
