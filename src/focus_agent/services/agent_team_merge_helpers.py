from __future__ import annotations

import json

from focus_agent.core.agent_team import (
    AgentTeamFinalAnswerStatus,
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)

from .agent_team_helpers import _dedupe

_REVIEW_EVIDENCE_ROLES = {
    "reviewer",
    "test_engineer",
    "verifier",
}
_STRONG_EVIDENCE_ROLES = {
    "backend_executor",
    "frontend_executor",
    "reviewer",
    "test_engineer",
    "verifier",
    "writer",
}
_REAL_EXECUTION_CLASSES = {
    "real_tool_loop",
    "sandbox_verified",
    "tool_agent",
    "worktree_sandbox",
}
_UNTRUSTWORTHY_EXECUTION_CLASSES = {
    "fake",
    "model_text",
}
_WORKTREE_HASH_KEYS = (
    "worktree_digest",
    "worktree_hash",
    "worktree_sha256",
    "workspace_digest",
    "workspace_hash",
    "workspace_sha256",
)
_DIFF_HASH_KEYS = (
    "diff_digest",
    "diff_hash",
    "diff_sha256",
    "patch_digest",
    "patch_hash",
    "patch_sha256",
)


def _strong_evidence_gate_violations(
    *,
    tasks: list[AgentTeamTask],
    outputs: list[AgentTeamTaskOutput],
) -> list[str]:
    """Return merge-blocking provenance gaps for explicitly tool-backed tasks."""
    outputs_by_task: dict[str, list[AgentTeamTaskOutput]] = {}
    for output in outputs:
        outputs_by_task.setdefault(output.task_id, []).append(output)

    violations: list[str] = []
    for task in tasks:
        if task.role.value not in _STRONG_EVIDENCE_ROLES:
            continue
        records: list[AgentTeamTask | AgentTeamTaskOutput] = [
            task,
            *outputs_by_task.get(task.task_id, []),
        ]
        claims = [_evidence_claim(record) for record in records]
        if not any(claim["declared"] for claim in claims):
            continue

        label = task.title or task.goal or task.task_id
        execution_classes = {value for claim in claims for value in claim["execution_classes"]}
        fallback_values = [value for claim in claims for value in claim["fallback_values"]]
        if execution_classes & _UNTRUSTWORTHY_EXECUTION_CLASSES:
            violations.append(
                "Strong evidence gate rejected "
                f"{task.role.value} task '{label}': execution_class is "
                f"{', '.join(sorted(execution_classes & _UNTRUSTWORTHY_EXECUTION_CLASSES))}."
            )
        if any(not _is_false(value) for value in fallback_values):
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "fallback_used must be false."
            )

        if not execution_classes:
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "execution_class is required for declared evidence."
            )
            continue
        if not execution_classes & _REAL_EXECUTION_CLASSES:
            continue

        evidence_levels = {value for claim in claims for value in claim["evidence_levels"]}
        evidence_verdicts = {value for claim in claims for value in claim["evidence_verdicts"]}
        sandbox_backends = {value for claim in claims for value in claim["sandbox_backends"]}
        command_exit_codes = [value for claim in claims for value in claim["command_exit_codes"]]
        worktree_hashes = [value for claim in claims for value in claim["worktree_hashes"]]
        diff_hashes = [value for claim in claims for value in claim["diff_hashes"]]

        if "verified" not in evidence_levels:
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "verified evidence_level is required."
            )
        if "verified" not in evidence_verdicts:
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "verified evidence_verdict is required."
            )
        if not any(_is_docker_backend(value) for value in sandbox_backends):
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "Docker sandbox evidence is required."
            )
        if not fallback_values:
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "fallback_used=false evidence is required."
            )
        if not command_exit_codes or any(
            not _is_success_exit_code(value) for value in command_exit_codes
        ):
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "successful command exit_code=0 evidence is required."
            )
        if not worktree_hashes:
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "worktree hash evidence is required."
            )
        if not diff_hashes:
            violations.append(
                f"Strong evidence gate rejected {task.role.value} task '{label}': "
                "diff hash evidence is required."
            )
    return _dedupe(violations)


def _evidence_claim(record: AgentTeamTask | AgentTeamTaskOutput) -> dict[str, object]:
    metadata = getattr(record, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    evidence_payloads = _mapping_values(metadata.get("evidence"))
    declared_contract = _declared_execution_contract(record)
    metadata_mappings = list(_nested_mappings(metadata))
    evidence_mappings = list(_nested_mappings(evidence_payloads))
    contract_mappings = [declared_contract, *evidence_mappings]
    all_mappings = [*contract_mappings, *metadata_mappings]
    execution_classes = _normalized_values(
        _values_from_mappings(
            all_mappings, "execution_class", "execution_mode", "execution_profile"
        )
    )
    return {
        "declared": bool(declared_contract or evidence_payloads)
        or bool(execution_classes & (_REAL_EXECUTION_CLASSES | _UNTRUSTWORTHY_EXECUTION_CLASSES)),
        "execution_classes": execution_classes,
        "evidence_levels": _normalized_values(
            _values_from_mappings(contract_mappings, "evidence_level")
        ),
        "evidence_verdicts": _normalized_values(
            _values_from_mappings(contract_mappings, "evidence_verdict")
        ),
        "sandbox_backends": _normalized_values(
            _values_from_mappings(contract_mappings, "sandbox_backend")
        ),
        "fallback_values": _values_from_mappings(contract_mappings, "fallback_used"),
        "command_exit_codes": _values_from_mappings(contract_mappings, "exit_code"),
        "worktree_hashes": _hash_values(contract_mappings, _WORKTREE_HASH_KEYS, "worktree"),
        "diff_hashes": _hash_values(contract_mappings, _DIFF_HASH_KEYS, "diff"),
    }


def _declared_execution_contract(
    record: AgentTeamTask | AgentTeamTaskOutput,
) -> dict[str, object]:
    fields_set = set(getattr(record, "model_fields_set", set()))
    values: dict[str, object] = {}
    for field in (
        "execution_class",
        "evidence_level",
        "evidence_verdict",
        "execution_profile",
        "sandbox_id",
    ):
        if field not in fields_set:
            continue
        value = getattr(record, field, None)
        if value is not None and str(value).strip():
            values[field] = value
    if _is_default_legacy_contract(values):
        return {}
    return values


def _is_default_legacy_contract(values: dict[str, object]) -> bool:
    return (
        values.get("execution_class") is None
        and str(
            getattr(values.get("evidence_level"), "value", values.get("evidence_level"))
        ).lower()
        == "synthetic"
        and str(
            getattr(values.get("evidence_verdict"), "value", values.get("evidence_verdict"))
        ).lower()
        == "unknown"
        and not values.get("execution_profile")
        and not values.get("sandbox_id")
    )


def _mapping_values(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _nested_mappings(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict):
        mappings = [value]
        for child in value.values():
            mappings.extend(_nested_mappings(child))
        return mappings
    if isinstance(value, list):
        mappings: list[dict[str, object]] = []
        for child in value:
            mappings.extend(_nested_mappings(child))
        return mappings
    return []


def _values_from_mappings(
    mappings: list[dict[str, object]],
    *keys: str,
) -> list[object]:
    values: list[object] = []
    for mapping in mappings:
        for key in keys:
            if key in mapping and mapping[key] is not None:
                values.append(mapping[key])
    return values


def _normalized_values(values: list[object]) -> set[str]:
    return {
        str(getattr(value, "value", value)).strip().lower()
        for value in values
        if str(getattr(value, "value", value)).strip()
    }


def _hash_values(
    mappings: list[dict[str, object]],
    keys: tuple[str, ...],
    nested_key: str,
) -> list[str]:
    values = [
        str(value).strip() for value in _values_from_mappings(mappings, *keys) if str(value).strip()
    ]
    for mapping in mappings:
        nested = mapping.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in ("digest", "hash", "sha256"):
            value = nested.get(key)
            if value is not None and str(value).strip():
                values.append(str(value).strip())
    return _dedupe(values)


def _is_docker_backend(value: str) -> bool:
    return value == "docker" or value.startswith("docker_") or value.startswith("docker-")


def _is_false(value: object) -> bool:
    return value is False or value == 0 or str(value).strip().lower() in {"0", "false", "no"}


def _is_success_exit_code(value: object) -> bool:
    return not isinstance(value, bool) and str(value).strip() == "0"


def _execution_evidence(
    *,
    tasks: list[AgentTeamTask],
    outputs: list[AgentTeamTaskOutput],
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, tuple[str, ...]]] = set()

    def append_item(item: dict[str, object]) -> None:
        artifact_ids = _dedupe(str(value) for value in item.get("artifact_ids", []) or [])
        canonical: dict[str, object] = {"task_id": str(item.get("task_id") or "")}
        role = str(item.get("role") or "").strip()
        if role:
            canonical["role"] = role
        for field in (
            "agent_run_id",
            "delegated_task_id",
            "execution_status",
            "workspace_id",
            "workspace_branch",
            "workspace_path",
            "base_commit",
            "workspace_status",
        ):
            value = str(item.get(field) or "").strip()
            if value:
                canonical[field] = value
        diff_summary = str(item.get("diff_summary") or "").strip()
        if diff_summary:
            canonical["diff_summary"] = diff_summary
        if artifact_ids:
            canonical["artifact_ids"] = artifact_ids
        key = (
            str(canonical.get("task_id") or ""),
            str(canonical.get("agent_run_id") or ""),
            str(canonical.get("delegated_task_id") or ""),
            str(canonical.get("execution_status") or ""),
            tuple(artifact_ids),
        )
        if key not in seen and any(key[1:]):
            seen.add(key)
            evidence.append(canonical)

    for task in tasks:
        append_item(
            {
                "task_id": task.task_id,
                "role": task.role.value,
                "agent_run_id": task.agent_run_id,
                "delegated_task_id": task.delegated_task_id,
                "artifact_ids": task.artifact_ids,
                "execution_status": task.execution_status,
                "workspace_id": task.workspace_id,
                "workspace_branch": task.workspace_branch,
                "workspace_path": task.workspace_path,
                "base_commit": task.base_commit,
                "diff_summary": task.diff_summary,
                "workspace_status": task.workspace_status,
            }
        )

    for output in outputs:
        execution_metadata = output.metadata.get("execution")
        if not isinstance(execution_metadata, dict):
            execution_metadata = {
                key: output.metadata[key]
                for key in (
                    "agent_run_id",
                    "delegated_task_id",
                    "artifact_ids",
                    "execution_status",
                    "workspace_id",
                    "workspace_branch",
                    "workspace_path",
                    "base_commit",
                    "diff_summary",
                    "workspace_status",
                )
                if key in output.metadata
            }
        if execution_metadata:
            append_item({"task_id": output.task_id, **execution_metadata})

    return evidence


def _missing_required_evidence(
    *, tasks: list[AgentTeamTask], outputs: list[AgentTeamTaskOutput]
) -> list[str]:
    outputs_by_task: dict[str, list[AgentTeamTaskOutput]] = {}
    for output in outputs:
        outputs_by_task.setdefault(output.task_id, []).append(output)

    missing: list[str] = []
    for task in tasks:
        if task.status != AgentTeamTaskStatus.DONE or not task.evidence_required:
            continue
        available = "\n".join(
            _dedupe(
                [task.verification_summary or ""]
                + task.risk_notes
                + task.changed_files
                + [output.summary for output in outputs_by_task.get(task.task_id, [])]
                + [
                    item
                    for output in outputs_by_task.get(task.task_id, [])
                    for item in output.test_evidence
                ]
                + [
                    item
                    for output in outputs_by_task.get(task.task_id, [])
                    for item in output.changed_files
                ]
                + [
                    item
                    for output in outputs_by_task.get(task.task_id, [])
                    for item in output.risk_notes
                ]
                + [
                    value
                    for output in outputs_by_task.get(task.task_id, [])
                    for value in _artifact_payload_values(output.metadata)
                ]
            )
        ).lower()
        missing_items = [
            item
            for item in task.evidence_required
            if str(item).strip() and str(item).strip().lower() not in available
        ]
        if missing_items:
            label = task.title or task.goal
            missing.append(
                f"Missing required evidence for {task.role.value} task '{label}': {', '.join(missing_items)}."
            )
    return _dedupe(missing)


def _merge_test_evidence(
    *, tasks: list[AgentTeamTask], outputs: list[AgentTeamTaskOutput]
) -> list[str]:
    values: list[str] = []
    for output in outputs:
        values.extend(_explicit_evidence_items(output.test_evidence))
    values.extend(
        _explicit_evidence_items(
            _metadata_values(outputs, "test_evidence", "verification_evidence", "tests")
        )
    )
    values.extend(
        _explicit_evidence_items(
            [
                task.verification_summary or ""
                for task in tasks
                if task.role.value in _REVIEW_EVIDENCE_ROLES
            ]
        )
    )
    return _dedupe(values)


def _has_review_or_verification_evidence(
    *,
    tasks: list[AgentTeamTask],
    outputs: list[AgentTeamTaskOutput],
) -> bool:
    task_by_id = {task.task_id: task for task in tasks}
    for output in outputs:
        task = task_by_id.get(output.task_id)
        role = task.role.value if task is not None else ""
        if _explicit_evidence_items(
            [
                *output.test_evidence,
                *_values_for_keys(
                    output.metadata, "test_evidence", "verification_evidence", "tests"
                ),
            ]
        ):
            return True
        if role not in _REVIEW_EVIDENCE_ROLES and output.kind.value not in {
            "review_report",
            "test_report",
        }:
            continue
        if output.summary or output.artifact_id or output.metadata:
            return True
    return any(
        task.role.value in _REVIEW_EVIDENCE_ROLES and bool(task.verification_summary)
        for task in tasks
    )


def _build_final_answer(
    *,
    session: AgentTeamSession,
    tasks: list[AgentTeamTask],
    outputs: list[AgentTeamTaskOutput],
    open_questions: list[str],
    risk_items: list[str],
) -> dict[str, object]:
    source_output_ids = _dedupe(output.output_id for output in outputs if output.output_id)
    if not outputs:
        return {
            "status": AgentTeamFinalAnswerStatus.BLOCKED,
            "answer": (f"Agent Team 尚未产生可汇总的任务回传，无法回答：{session.goal}"),
            "warnings": ["No task outputs are available for final answer synthesis."],
            "source_output_ids": source_output_ids,
        }

    if _has_fake_outputs(outputs):
        return {
            "status": AgentTeamFinalAnswerStatus.PLACEHOLDER,
            "answer": (
                "当前是模拟执行，只验证了 Agent Team 的拆解、运行和回传流程，"
                f"没有生成可交付的真实答案。请使用真实模型执行后再生成最终答案。\n\n目标：{session.goal}"
            ),
            "warnings": [
                "Current mission outputs were produced by fake execution mode.",
                "Fake execution validates workflow only; it must not be treated as a deliverable final answer.",
            ],
            "source_output_ids": source_output_ids,
        }

    if not _has_executor_or_writer_output(tasks=tasks, outputs=outputs):
        return {
            "status": AgentTeamFinalAnswerStatus.BLOCKED,
            "answer": (
                "Agent Team 已有部分任务回传，但缺少执行/撰写任务产出，"
                f"暂时无法形成面向用户目标的最终答案。\n\n目标：{session.goal}"
            ),
            "warnings": ["Missing executor or writer output for final answer synthesis."],
            "source_output_ids": source_output_ids,
        }

    body_items = _final_answer_content_items(_deliverable_outputs(tasks=tasks, outputs=outputs))
    if not body_items:
        return {
            "status": AgentTeamFinalAnswerStatus.BLOCKED,
            "answer": (
                f"Agent Team 已完成任务，但回传内容为空，无法形成最终答案。\n\n目标：{session.goal}"
            ),
            "warnings": ["Task outputs did not include summary, raw_text, or parsed content."],
            "source_output_ids": source_output_ids,
        }

    warnings = _dedupe([*risk_items, *open_questions])
    sections = [
        f"目标：{session.goal}",
        "Agent Team 最终答案：",
        *[f"{index}. {item}" for index, item in enumerate(body_items, start=1)],
    ]
    if warnings:
        sections.extend(["需要注意：", *[f"- {item}" for item in warnings]])
    return {
        "status": AgentTeamFinalAnswerStatus.READY,
        "answer": "\n".join(sections),
        "warnings": warnings,
        "source_output_ids": source_output_ids,
    }


def _has_fake_outputs(outputs: list[AgentTeamTaskOutput]) -> bool:
    for output in outputs:
        execution = output.metadata.get("execution")
        execution_mode = execution.get("execution_mode") if isinstance(execution, dict) else None
        if str(execution_mode or "").strip().lower() == "fake":
            return True
        run = output.metadata.get("run")
        run_execution_mode = run.get("execution_mode") if isinstance(run, dict) else None
        if str(run_execution_mode or "").strip().lower() == "fake":
            return True
        if str(output.metadata.get("execution_mode") or "").strip().lower() == "fake":
            return True
        if output.summary.strip().lower().startswith("fake delegated"):
            return True
    return False


def _has_executor_or_writer_output(
    *, tasks: list[AgentTeamTask], outputs: list[AgentTeamTaskOutput]
) -> bool:
    task_by_id = {task.task_id: task for task in tasks}
    for output in outputs:
        task = task_by_id.get(output.task_id)
        if task is None:
            continue
        if task.role in {
            AgentTeamTaskRole.BACKEND_EXECUTOR,
            AgentTeamTaskRole.FRONTEND_EXECUTOR,
            AgentTeamTaskRole.WRITER,
        }:
            return True
    return False


def _deliverable_outputs(
    *, tasks: list[AgentTeamTask], outputs: list[AgentTeamTaskOutput]
) -> list[AgentTeamTaskOutput]:
    task_by_id = {task.task_id: task for task in tasks}
    deliverable_roles = {
        AgentTeamTaskRole.BACKEND_EXECUTOR,
        AgentTeamTaskRole.FRONTEND_EXECUTOR,
        AgentTeamTaskRole.WRITER,
    }
    deliverables = [
        output
        for output in outputs
        if task_by_id.get(output.task_id) is not None
        and task_by_id[output.task_id].role in deliverable_roles
    ]
    return deliverables or outputs


def _final_answer_content_items(outputs: list[AgentTeamTaskOutput]) -> list[str]:
    items: list[str] = []
    for output in outputs:
        items.extend(_artifact_payload_values(output.metadata))
        if output.summary:
            items.append(output.summary)
    return _dedupe(item.strip() for item in items if item and item.strip())


def _artifact_payload_values(metadata: dict[str, object]) -> list[str]:
    values: list[str] = []
    direct_payload = metadata.get("payload")
    if isinstance(direct_payload, dict):
        values.extend(_payload_values(direct_payload))
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, list):
        return values
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        payload = artifact.get("payload")
        if not isinstance(payload, dict):
            continue
        values.extend(_payload_values(payload))
    return values


def _payload_values(payload: dict[str, object]) -> list[str]:
    values: list[str] = []
    raw_text = payload.get("raw_text")
    if isinstance(raw_text, str) and raw_text.strip():
        values.append(raw_text)
    parsed = payload.get("parsed")
    if isinstance(parsed, dict):
        extracted = False
        for key in ("summary", "final_answer", "answer", "findings"):
            raw = parsed.get(key)
            if isinstance(raw, str) and raw.strip():
                values.append(raw)
                extracted = True
            elif isinstance(raw, list):
                values.extend(str(item) for item in raw if item)
                extracted = True
        if not extracted:
            values.append(json.dumps(parsed, ensure_ascii=False, sort_keys=True))
    elif isinstance(parsed, list):
        values.extend(str(item) for item in parsed if item)
    elif isinstance(parsed, str) and parsed.strip():
        values.append(parsed)
    return values


def _explicit_evidence_items(values: list[str]) -> list[str]:
    return [value for value in values if _is_explicit_evidence(value)]


def _is_explicit_evidence(value: str) -> bool:
    text = value.strip().lower()
    return (
        bool(text)
        and not text.startswith("delegated ")
        and not text.startswith("completed ")
        and text != "completed"
    )


def _planning_risk_notes(
    *, session: AgentTeamSession, outputs: list[AgentTeamTaskOutput]
) -> list[str]:
    values: list[str] = []
    latest_bundle = session.latest_merge_bundle or {}
    if isinstance(latest_bundle, dict):
        values.extend(_values_for_keys(latest_bundle, "risk_items", "risk_notes", "risks"))
    for output in outputs:
        values.extend(
            _values_for_keys(
                output.metadata,
                "risk_items",
                "risk_notes",
                "risks",
                "open_risks",
            )
        )
        planning = output.metadata.get("planning")
        if isinstance(planning, dict):
            values.extend(
                _values_for_keys(
                    planning,
                    "risk_items",
                    "risk_notes",
                    "risks",
                    "open_risks",
                )
            )
    return _dedupe(values)


def _metadata_values(outputs: list[AgentTeamTaskOutput], *keys: str) -> list[str]:
    values: list[str] = []
    for output in outputs:
        values.extend(_values_for_keys(output.metadata, *keys))
    return _dedupe(values)


def _values_for_keys(payload: dict[str, object], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = payload.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
    return values


__all__ = [
    "_build_final_answer",
    "_execution_evidence",
    "_has_fake_outputs",
    "_has_review_or_verification_evidence",
    "_merge_test_evidence",
    "_missing_required_evidence",
    "_planning_risk_notes",
    "_strong_evidence_gate_violations",
]
