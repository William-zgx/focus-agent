from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

MEMORY_LAYER_EVALUATION_LIMITATION = (
    "Synthetic markers diagnose canonical writes, retrieval, and deterministic prompt use. "
    "They do not measure generative quality or human attention. A new explicit assertion "
    "after forget is reported separately from resurrection of the forgotten memory ID."
)


def evaluate_memory_layer_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(observation.get("case_id") or "")
    failures = {"write": [], "retrieval": [], "use": []}
    expected = observation.get("expected")
    if (
        not case_id
        or not isinstance(observation.get("write"), Mapping)
        or not isinstance(observation.get("retrieval"), Mapping)
        or not isinstance(observation.get("use"), Mapping)
        or not isinstance(expected, Mapping)
        or not expected
    ):
        failures["write"].append("invalid_observation")
        return {
            "case_id": case_id,
            "active_record_count": 0,
            "selected_memory_ids": [],
            "recreated_record_ids": [],
            "layer_failures": failures,
            "hard_stop_violations": [],
            "passed": False,
        }
    write = observation["write"]
    retrieval = observation["retrieval"]
    use = observation["use"]
    records = list(write.get("records") or [])
    selected_ids = [str(item) for item in retrieval.get("selected_memory_ids") or []]
    scoped_text = str(use.get("scoped_prompt") or "")
    use_text = "\n".join(str(use.get(key) or "") for key in ("prompt", "scoped_prompt"))
    hard_stops: list[str] = []
    active_records = [record for record in records if _active(record)]
    active_text = "\n".join(
        f"{record.get('summary', '')} {record.get('content', '')}" for record in active_records
    )
    if "active_record_count" in expected and len(active_records) != int(
        expected["active_record_count"]
    ):
        failures["write"].append(
            f"active_record_count:{len(active_records)}!={expected['active_record_count']}"
        )
    if "selected_memory_ids" in expected and set(selected_ids) != {
        str(item) for item in expected["selected_memory_ids"]
    }:
        failures["retrieval"].append("selected_memory_ids_mismatch")
    for marker in expected.get("required_use_markers") or []:
        if str(marker) not in scoped_text:
            failures["use"].append(f"missing_required_marker:{marker}")
    forgotten_ids = {str(item) for item in expected.get("forgotten_memory_ids") or []}
    for memory_id in sorted(forgotten_ids & set(selected_ids)):
        hard_stops.append(f"forgotten_memory_selected:{memory_id}")
        failures["retrieval"].append(f"forgotten_memory_selected:{memory_id}")
    for record in records:
        memory_id = str(record.get("memory_id") or "")
        if memory_id in forgotten_ids and _active(record):
            hard_stops.append(f"forgotten_memory_resurrected:{memory_id}")
            failures["write"].append(f"forgotten_memory_active:{memory_id}")
    for marker in expected.get("forgotten_markers") or []:
        if str(marker) in use_text:
            hard_stops.append(f"forgotten_marker_in_use:{marker}")
            failures["use"].append(f"forgotten_marker:{marker}")
    foreign_ids = {str(item) for item in expected.get("foreign_memory_ids") or []}
    for memory_id in sorted(foreign_ids & set(selected_ids)):
        hard_stops.append(f"cross_owner_memory_selected:{memory_id}")
        failures["retrieval"].append(f"foreign_memory_selected:{memory_id}")
    for marker in expected.get("foreign_markers") or []:
        if str(marker) in use_text:
            hard_stops.append(f"cross_owner_marker_in_use:{marker}")
            failures["use"].append(f"foreign_marker:{marker}")
    for marker in expected.get("stale_decision_markers") or []:
        if str(marker) in active_text:
            hard_stops.append(f"stale_decision_active:{marker}")
            failures["write"].append(f"stale_decision_marker:{marker}")
        if str(marker) in use_text:
            hard_stops.append(f"stale_decision_in_use:{marker}")
            failures["use"].append(f"stale_decision_marker:{marker}")
    return {
        "case_id": case_id,
        "active_record_count": len(active_records),
        "selected_memory_ids": selected_ids,
        "recreated_record_ids": [
            str(item) for item in observation.get("recreated_record_ids") or []
        ],
        "layer_failures": failures,
        "hard_stop_violations": list(dict.fromkeys(hard_stops)),
        "passed": not any(failures.values()) and not hard_stops,
    }


def evaluate_memory_layer_suite(observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    cases = [evaluate_memory_layer_observation(observation) for observation in observations]
    return {
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "passed": bool(cases) and all(case["passed"] for case in cases),
            "hard_stop_violation_count": sum(len(case["hard_stop_violations"]) for case in cases),
        },
        "limitation": MEMORY_LAYER_EVALUATION_LIMITATION,
    }


def _active(record: Mapping[str, Any]) -> bool:
    status = getattr(record.get("status", "active"), "value", record.get("status", "active"))
    return status == "active" and record.get("deleted_at") is None


__all__ = [
    "MEMORY_LAYER_EVALUATION_LIMITATION",
    "evaluate_memory_layer_observation",
    "evaluate_memory_layer_suite",
]
