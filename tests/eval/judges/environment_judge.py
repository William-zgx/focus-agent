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
        before_state: Mapping[str, Any] | None = None,  # noqa: ARG002
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
        initial_state = _initial_state(case)

        for index, assertion in enumerate(assertions):
            detail = _evaluate_assertion(
                index=index,
                assertion=assertion,
                state=state or {},
                initial_state=initial_state,
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
    state: Mapping[str, Any],
    initial_state: Mapping[str, Any],
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

    value, source = _resolve_with_fallback(path=path, state=state, initial_state=initial_state)
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
        failures.append(
            f"assertion[{index}] path={path!r} not found in final state or initial_state"
        )
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
                f"assertion[{index}] path={path!r} len={actual_len} "
                f"exceeded max_len={expected_max}"
            )

    if len(detail["checks"]) == checks_before_value_assertions:
        detail["checks"].append("exists")

    return detail


def _resolve_with_fallback(
    *,
    path: str,
    state: Mapping[str, Any],
    initial_state: Mapping[str, Any],
) -> tuple[Any, str | None]:
    value = _resolve_path(state, path)
    if value is not _MISSING:
        return value, "state"
    value = _resolve_path(initial_state, path)
    if value is not _MISSING:
        return value, "initial_state"
    return _MISSING, None


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
