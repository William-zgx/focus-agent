from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from focus_agent.config import Settings
from focus_agent.eval.trajectory_replay import (
    build_replay_comparison,
    convert_trajectory_records,
)
from focus_agent.repositories.postgres_trajectory_repository import (
    PostgresTrajectoryRepository,
    TrajectoryTurnQuery,
)


def _load_replay_runtime():
    from focus_agent.eval.runner import build_default_runtime, run_case

    return build_default_runtime, run_case


def load_turn_export(
    repo: PostgresTrajectoryRepository | Any,
    *,
    turn_id: str,
) -> dict[str, Any] | None:
    rows = repo.export_turns(TrajectoryTurnQuery(turn_ids=[turn_id], limit=1))
    if not rows:
        return None
    return dict(rows[0])


def build_promoted_dataset_payload(
    record: dict[str, Any],
    *,
    case_id_prefix: str = "traj",
    copy_tool_trajectory: bool = False,
    copy_answer_substring: bool = False,
    answer_substring_chars: int = 160,
) -> dict[str, Any]:
    converted = convert_trajectory_records(
        [record],
        case_id_prefix=case_id_prefix,
        copy_tool_trajectory=copy_tool_trajectory,
        copy_answer_substring=copy_answer_substring,
        answer_substring_chars=answer_substring_chars,
    )
    if not converted:
        raise ValueError("failed to convert trajectory record")
    case = converted[0].case
    dataset_record = {
        "id": case.id,
        "input": case.input,
        "expected": case.expected,
        "tags": case.tags,
        "scene": case.scene,
        "skill_hints": case.skill_hints,
        "setup": case.setup,
        "judge": case.judge,
        "origin": case.origin,
    }
    return {
        "source_turn_id": str(record.get("id") or ""),
        "case_id": case.id,
        "dataset_record": dataset_record,
        "jsonl": json.dumps(dataset_record, ensure_ascii=False),
    }


def run_replay_for_turn(
    record: dict[str, Any],
    *,
    settings: Settings,
    model: str | None = None,
    case_id_prefix: str = "traj",
    copy_tool_trajectory: bool = False,
    copy_answer_substring: bool = False,
    answer_substring_chars: int = 160,
) -> dict[str, Any]:
    build_default_runtime, run_case = _load_replay_runtime()
    converted = convert_trajectory_records(
        [record],
        case_id_prefix=case_id_prefix,
        copy_tool_trajectory=copy_tool_trajectory,
        copy_answer_substring=copy_answer_substring,
        answer_substring_chars=answer_substring_chars,
    )
    if not converted:
        raise ValueError("failed to convert trajectory record")
    converted_case = converted[0]
    replay_settings = replace(settings)
    if model:
        replay_settings.model = model
    runtime = build_default_runtime(settings=replay_settings)
    result = run_case(converted_case.case, runtime=runtime)
    comparison = build_replay_comparison(record, result)
    return {
        "source_turn_id": str(record.get("id") or ""),
        "replay_case": {
            "id": converted_case.case.id,
            "input": converted_case.case.input,
            "expected": converted_case.case.expected,
            "tags": converted_case.case.tags,
            "scene": converted_case.case.scene,
            "origin": converted_case.case.origin,
        },
        "replay_result": result.to_dict(),
        "comparison": comparison,
    }
