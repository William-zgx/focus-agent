from __future__ import annotations

from typing import Any

from focus_agent.core.agent_team import (
    AgentTeamMergeReview,
    AgentTeamTask,
    AgentTeamTaskOutput,
)

from .agent_team_helpers import _dedupe
from .agent_team_merge_helpers import _has_fake_outputs
from .agent_team_merge_review_git import (
    git_changed_files as _git_changed_files,
)
from .agent_team_merge_review_git import (
    git_diff_for_workspace as _git_diff_for_workspace,
)
from .agent_team_merge_review_git import (
    git_diffstat as _git_diffstat,
)


def _build_merge_review_preview(
    *,
    review: AgentTeamMergeReview,
    tasks: list[AgentTeamTask],
    outputs: list[AgentTeamTaskOutput],
) -> dict[str, Any]:
    outputs_by_task: dict[str, list[AgentTeamTaskOutput]] = {}
    for output in outputs:
        outputs_by_task.setdefault(output.task_id, []).append(output)
    task_summaries: list[dict[str, Any]] = []
    changed_files: list[str] = []
    test_evidence: list[str] = []
    risk_items: list[str] = []
    diffstats: list[str] = []
    patches: list[str] = []
    non_adoptable_task_ids: list[str] = []
    for task in tasks:
        task_outputs = outputs_by_task.get(task.task_id, [])
        workspace_patch = _git_diff_for_workspace(task.workspace_path, task.base_commit)
        workspace_changed = _git_changed_files(task.workspace_path, task.base_commit)
        workspace_diffstat = _git_diffstat(task.workspace_path, task.base_commit)
        task_fake = _task_has_fake_or_placeholder_output(task=task, outputs=task_outputs)
        adoptable = not task_fake
        if not adoptable:
            non_adoptable_task_ids.append(task.task_id)
        task_changed = _dedupe(
            [
                *task.changed_files,
                *(path for output in task_outputs for path in output.changed_files),
                *workspace_changed,
            ]
        )
        task_tests = _dedupe(
            [
                *task.test_evidence,
                *(item for output in task_outputs for item in output.test_evidence),
            ]
        )
        task_risks = _dedupe(
            [
                *task.risk_notes,
                *(item for output in task_outputs for item in output.risk_notes),
            ]
        )
        changed_files.extend(task_changed)
        test_evidence.extend(task_tests)
        risk_items.extend(task_risks)
        if workspace_diffstat:
            diffstats.append(workspace_diffstat)
        if workspace_patch and adoptable:
            patches.append(workspace_patch)
        task_summaries.append(
            {
                "task_id": task.task_id,
                "title": task.title,
                "role": task.role.value,
                "status": task.status.value,
                "workspace_path": task.workspace_path,
                "workspace_status": task.workspace_status,
                "changed_files": task_changed,
                "test_evidence": task_tests,
                "risk_items": task_risks,
                "adoptable": adoptable,
                "non_adoptable_reason": "fake_or_placeholder_output" if task_fake else None,
                "output_ids": [output.output_id for output in task_outputs],
            }
        )
    changed_files = _dedupe(changed_files)
    patch = "\n".join(item.rstrip() for item in patches if item.strip())
    if patch:
        patch = f"{patch}\n"
    return {
        "summary": (
            f"{len(tasks)} selected tasks, {len(changed_files)} changed files ready for review."
        ),
        "changed_files": changed_files,
        "diffstat": "\n".join(item for item in diffstats if item),
        "test_evidence": _dedupe(test_evidence),
        "risk_items": _dedupe(risk_items),
        "task_summaries": task_summaries,
        "patch": patch,
        "non_adoptable_task_ids": non_adoptable_task_ids,
    }


def _task_has_fake_or_placeholder_output(
    *,
    task: AgentTeamTask,
    outputs: list[AgentTeamTaskOutput],
) -> bool:
    if str(task.execution_mode or "").strip().lower() == "fake":
        return True
    if str(task.run_status or "").strip().lower() == "placeholder":
        return True
    return _has_fake_outputs(outputs) or any(
        str(output.metadata.get("final_answer_status") or "").strip().lower() == "placeholder"
        for output in outputs
    )


__all__ = ["_build_merge_review_preview"]
