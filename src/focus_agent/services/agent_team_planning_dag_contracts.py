from __future__ import annotations

from typing import Any

from .agent_team_planning_models import MissionDeliverable

_SANDBOX_TASK_MARKERS = {
    "build",
    "debug",
    "debugging",
    "execution",
    "implementation",
    "test",
    "testing",
    "verification",
}
_SANDBOX_CAPABILITY_MARKERS = (
    "build",
    "code modification",
    "command",
    "execution",
    "node",
    "pytest",
    "python",
    "sandbox",
    "test execution",
)


def _dedupe_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _resource_claims_for_deliverable(
    deliverable: MissionDeliverable,
    *,
    sandbox_id: str | None = None,
) -> list[str]:
    claims = list(deliverable.resource_claims or _resource_claims_for_scope(deliverable.write_scope))
    if sandbox_id and _deliverable_requires_sandbox(deliverable):
        claims.append(f"sandbox:{_sanitize_resource_identifier(sandbox_id)}")
    return _dedupe_values(claims)


def _resource_claims_for_scope(write_scope: list[str]) -> list[str]:
    claims: list[str] = []
    for item in write_scope:
        text = str(item or "").strip()
        if text:
            claims.append(f"file:{text}")
    return _dedupe_values(claims)


def _deliverable_requires_sandbox(deliverable: MissionDeliverable) -> bool:
    task_markers = {
        str(deliverable.task_type or "").strip().lower(),
        str(deliverable.task_kind or "").strip().lower(),
    }
    if any(marker in _SANDBOX_TASK_MARKERS for marker in task_markers):
        return True
    capabilities = " ".join(str(item or "").strip().lower() for item in deliverable.capability_requirements)
    return any(marker in capabilities for marker in _SANDBOX_CAPABILITY_MARKERS)


def _sanitize_resource_identifier(value: str) -> str:
    text = str(value or "").strip()
    sanitized = "".join(char if char.isalnum() or char in "_.-" else "-" for char in text)
    sanitized = sanitized.strip(".-_")
    return sanitized or "anonymous"


def _contract_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _dedupe_values([value])
    return _dedupe_values([str(item) for item in value if str(item).strip()])


def _apply_contract_defaults(task_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [dict(spec) for spec in task_specs]
    output_by_key = {
        str(spec.get("key")): _contract_values(
            spec.get("output_items") or [str(spec.get("task_type") or "output")]
        )
        for spec in specs
    }
    for spec in specs:
        task_type = str(spec.get("task_type") or "execution")
        dependencies = _contract_values(spec.get("dependencies"))
        input_items = _contract_values(spec.get("input_items"))
        for dependency in dependencies:
            input_items.extend(output_by_key.get(dependency, []))
        input_items = _dedupe_values(input_items)
        output_items = _contract_values(spec.get("output_items") or [task_type])
        evidence = _contract_values(spec.get("evidence_required") or spec.get("evidence"))
        capabilities = _contract_values(
            spec.get("capability_requirements") or spec.get("capabilities")
        )
        replan_when = _contract_values(spec.get("replan_when"))

        spec["dependencies"] = dependencies
        spec.setdefault("task_kind", task_type)
        spec.setdefault("output_items", output_items)
        if not isinstance(spec.get("input_contract"), dict):
            spec["input_contract"] = {
                "requires": input_items,
                "from_dependencies": dependencies,
            }
        if not isinstance(spec.get("output_contract"), dict):
            spec["output_contract"] = {"produces": output_items, "evidence": evidence}
        spec["evidence_required"] = evidence
        spec["capability_requirements"] = capabilities
        if not spec.get("risk_level") and spec.get("risk"):
            spec["risk_level"] = str(spec["risk"])
        if not isinstance(spec.get("replan_policy"), dict):
            spec["replan_policy"] = {"replan_when": replan_when}
    return specs


__all__ = [
    "_apply_contract_defaults",
    "_contract_values",
    "_dedupe_values",
    "_resource_claims_for_deliverable",
    "_resource_claims_for_scope",
]
