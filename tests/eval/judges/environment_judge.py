"""Environment/state judge for deterministic eval assertions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..schema import EvalCase, JudgeVerdict, TrajectoryStep

_MISSING = object()


class EnvironmentJudge:
    kind = "environment"

    def evaluate(
        self,
        *,
        case: EvalCase,
        answer: str,  # noqa: ARG002
        trajectory: list[TrajectoryStep],  # noqa: ARG002
        state: Mapping[str, Any] | None = None,
        before_state: Mapping[str, Any] | None = None,
    ) -> JudgeVerdict:
        assertions = _environment_assertions(case)
        if not assertions:
            return JudgeVerdict(
                kind=self.kind,
                passed=True,
                reasoning="no environment assertions set",
                confidence=1.0,
                details={"skipped": True, "checks_run": []},
            )

        failures: list[str] = []
        assertion_details: list[dict[str, Any]] = []
        final_state = state if state is not None else {}
        input_state = before_state if before_state is not None else _initial_state(case)

        for index, assertion in enumerate(assertions):
            detail = _evaluate_assertion(
                index=index,
                assertion=assertion,
                final_state=final_state,
                input_state=input_state,
                trajectory=trajectory,
            )
            assertion_details.append(detail)
            failures.extend(str(failure) for failure in detail.get("failures", []))

        return JudgeVerdict(
            kind=self.kind,
            passed=not failures,
            reasoning="; ".join(failures) if failures else "all environment checks passed",
            confidence=1.0,
            details={
                "checks_run": ["environment_assertions"],
                "failures": failures,
                "assertions": assertion_details,
            },
        )


def _environment_assertions(case: EvalCase) -> list[Mapping[str, Any]]:
    environment = _get_field(case, "environment")
    assertions = _get_field(environment, "assertions") if environment is not None else None
    if not assertions:
        return []
    if isinstance(assertions, Mapping):
        return [assertions]
    if isinstance(assertions, Sequence) and not isinstance(assertions, (str, bytes, bytearray)):
        return [item for item in assertions if isinstance(item, Mapping)]
    return []


def _initial_state(case: EvalCase) -> Mapping[str, Any]:
    input_payload = _get_field(case, "input") or {}
    initial_state = _get_field(input_payload, "initial_state")
    return initial_state if isinstance(initial_state, Mapping) else {}


def _evaluate_assertion(
    *,
    index: int,
    assertion: Mapping[str, Any],
    final_state: Mapping[str, Any],
    input_state: Mapping[str, Any],
    trajectory: list[TrajectoryStep],
) -> dict[str, Any]:
    path = assertion.get("path")
    failures: list[str] = []
    detail: dict[str, Any] = {
        "index": index,
        "path": path,
        "checks": [],
        "failures": failures,
    }

    if not isinstance(path, str) or not path:
        failures.append(f"assertion[{index}] missing non-empty path")
        return detail

    requested_source = _assertion_source(assertion)
    detail["source_requested"] = requested_source
    if requested_source == "input":
        value = _resolve_path(input_state, path)
        source = "input" if value is not _MISSING else None
    elif requested_source == "trajectory":
        value = _resolve_trajectory_path(trajectory, path)
        source = "trajectory" if value is not _MISSING else None
    elif requested_source == "final_state":
        value = _resolve_path(final_state, path)
        source = "final_state" if value is not _MISSING else None
    else:
        value = _MISSING
        source = None
        failures.append(
            f"assertion[{index}] path={path!r} has unsupported source={requested_source!r}"
        )
    exists = source is not None
    detail["source"] = source
    detail["exists"] = exists
    if exists:
        detail["actual"] = value

    if "exists" in assertion:
        detail["checks"].append("exists")
        expected_exists = bool(assertion["exists"])
        detail["expected_exists"] = expected_exists
        if exists != expected_exists:
            failures.append(
                f"assertion[{index}] path={path!r} exists={exists} expected {expected_exists}"
            )
        if not expected_exists:
            return detail

    if not exists:
        source_label = {
            "input": "input",
            "trajectory": "trajectory",
            "final_state": "final state",
        }.get(requested_source, requested_source)
        failures.append(f"assertion[{index}] path={path!r} not found in {source_label}")
        return detail

    checks_before_value_assertions = len(detail["checks"])

    if "equals" in assertion:
        detail["checks"].append("equals")
        expected = assertion["equals"]
        detail["expected_equals"] = expected
        if value != expected:
            failures.append(
                f"assertion[{index}] path={path!r} expected equals "
                f"{_format_value(expected)}, got {_format_value(value)}"
            )

    if "contains" in assertion:
        detail["checks"].append("contains")
        expected = assertion["contains"]
        detail["expected_contains"] = expected
        contains, reason = _contains_value(value, expected)
        if not contains:
            failures.append(
                f"assertion[{index}] path={path!r} expected contains "
                f"{_format_value(expected)}: {reason}"
            )

    if "not_contains" in assertion:
        detail["checks"].append("not_contains")
        forbidden = assertion["not_contains"]
        detail["expected_not_contains"] = forbidden
        contains, reason = _contains_value(value, forbidden)
        if contains:
            failures.append(
                f"assertion[{index}] path={path!r} must not contain "
                f"{_format_value(forbidden)}: {reason}"
            )

    if "min_len" in assertion:
        detail["checks"].append("min_len")
        expected_min = int(assertion["min_len"])
        detail["expected_min_len"] = expected_min
        actual_len = _safe_len(value)
        detail["actual_len"] = actual_len
        if actual_len is None:
            failures.append(f"assertion[{index}] path={path!r} has no length")
        elif actual_len < expected_min:
            failures.append(
                f"assertion[{index}] path={path!r} len={actual_len} "
                f"fell below min_len={expected_min}"
            )

    if "max_len" in assertion:
        detail["checks"].append("max_len")
        expected_max = int(assertion["max_len"])
        detail["expected_max_len"] = expected_max
        actual_len = _safe_len(value)
        detail["actual_len"] = actual_len
        if actual_len is None:
            failures.append(f"assertion[{index}] path={path!r} has no length")
        elif actual_len > expected_max:
            failures.append(
                f"assertion[{index}] path={path!r} len={actual_len} exceeded max_len={expected_max}"
            )

    if len(detail["checks"]) == checks_before_value_assertions:
        detail["checks"].append("exists")

    return detail


def _assertion_source(assertion: Mapping[str, Any]) -> str:
    raw = assertion.get("source", assertion.get("scope", "final_state"))
    source = str(raw or "final_state").strip().lower()
    aliases = {
        "state": "final_state",
        "final": "final_state",
        "final_state": "final_state",
        "input": "input",
        "initial": "input",
        "initial_state": "input",
        "trajectory": "trajectory",
        "execution": "trajectory",
    }
    return aliases.get(source, source)


def _resolve_trajectory_path(trajectory: list[TrajectoryStep], path: str) -> Any:
    snapshot = _trajectory_snapshot(trajectory)
    if path == "trajectory":
        return snapshot
    if path.startswith("trajectory."):
        return _resolve_path({"trajectory": snapshot}, path)
    return _resolve_path(snapshot, path)


def _trajectory_snapshot(trajectory: list[TrajectoryStep]) -> dict[str, Any]:
    roles: list[str] = []
    handoffs: list[str] = []
    for step in trajectory:
        step_roles = _role_values(
            [
                step.args.get("role"),
                step.args.get("agent_role"),
                step.runtime.get("role"),
                step.runtime.get("branch_role"),
                step.runtime.get("handoff_from"),
                step.runtime.get("handoff_to"),
            ]
        )
        for role in step_roles:
            if role not in roles:
                roles.append(role)
        current_roles = _role_values(
            [
                step.args.get("role"),
                step.args.get("agent_role"),
                step.runtime.get("role"),
                step.runtime.get("branch_role"),
            ]
        )
        source_roles = _role_values([step.runtime.get("handoff_from")])
        target_roles = _role_values([step.runtime.get("handoff_to")])
        if current_roles and target_roles:
            handoffs.extend(
                f"{source}->{target}" for source in current_roles for target in target_roles
            )
        if source_roles and current_roles:
            handoffs.extend(
                f"{source}->{target}" for source in source_roles for target in current_roles
            )
        if source_roles and target_roles:
            handoffs.extend(
                f"{source}->{target}" for source in source_roles for target in target_roles
            )

    return {
        "steps": [step.to_dict() for step in trajectory],
        "tools": [step.tool for step in trajectory],
        "roles": roles,
        "delegated_roles": roles,
        "handoffs": handoffs,
        "critic_runs": sum(1 for role in roles if role.lower() == "critic"),
    }


def _role_values(values: list[Any]) -> list[str]:
    roles: list[str] = []
    for value in values:
        candidates = value if isinstance(value, (list, tuple, set)) else [value]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text and text not in roles:
                roles.append(text)
    return roles


def _resolve_path(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        current = _resolve_part(current, part)
        if current is _MISSING:
            return _MISSING
    return current


def _resolve_part(current: Any, part: str) -> Any:
    if isinstance(current, Mapping):
        return current.get(part, _MISSING)
    if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
        if not part.isdigit():
            return _MISSING
        index = int(part)
        if index >= len(current):
            return _MISSING
        return current[index]
    return getattr(current, part, _MISSING)


def _contains_value(container: Any, expected: Any) -> tuple[bool, str]:
    if isinstance(container, str):
        if _is_many(expected):
            missing = [item for item in expected if str(item) not in container]
            if missing:
                return False, f"missing substrings {_format_value(missing)}"
            return True, "all substrings present"
        if str(expected) in container:
            return True, "substring present"
        return False, "substring missing"

    if isinstance(container, Mapping):
        if isinstance(expected, Mapping):
            mismatches = []
            for key, value in expected.items():
                if key not in container:
                    mismatches.append(f"missing key {key!r}")
                elif container[key] != value:
                    mismatches.append(
                        f"key {key!r} expected {_format_value(value)}, "
                        f"got {_format_value(container[key])}"
                    )
            if mismatches:
                return False, "; ".join(mismatches)
            return True, "mapping subset present"
        if _is_many(expected):
            missing = [item for item in expected if item not in container]
            if missing:
                return False, f"missing keys {_format_value(missing)}"
            return True, "all keys present"
        if expected in container:
            return True, "key present"
        return False, "key missing"

    if isinstance(container, Sequence) and not isinstance(container, (str, bytes, bytearray)):
        if _is_many(expected):
            missing = [item for item in expected if item not in container]
            if missing:
                return False, f"missing items {_format_value(missing)}"
            return True, "all items present"
        if expected in container:
            return True, "item present"
        return False, "item missing"

    return False, f"type {type(container).__name__} does not support contains"


def _safe_len(value: Any) -> int | None:
    try:
        return len(value)
    except TypeError:
        return None


def _is_many(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _get_field(value: Any, field: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(field)
    return getattr(value, field, None)


def _format_value(value: Any) -> str:
    rendered = repr(value)
    if len(rendered) > 200:
        return rendered[:197] + "..."
    return rendered
