from focus_agent.agent_delegation import build_agent_delegation_plan
from focus_agent.agent_task_ledger import (
    apply_critic_retry_tasks,
    build_agent_task_ledger,
    build_delegated_artifacts,
    evaluate_critic_gate,
    synthesize_delegated_artifacts,
)
from focus_agent.config import Settings


def test_task_ledger_default_off_is_legacy_safe():
    ledger = build_agent_task_ledger(settings=Settings(), delegation_plan={})

    assert ledger.enabled is False
    assert ledger.tasks == []


def test_task_ledger_converts_delegation_plan_to_task_dag():
    settings = Settings(
        agent_role_routing_enabled=True,
        agent_delegation_enabled=True,
        agent_delegation_enforce=True,
        agent_task_ledger_enabled=True,
    )
    delegation_plan = build_agent_delegation_plan(
        settings=settings,
        task_text="Plan, implement, and verify task ledger.",
        available_tool_names=["search_code"],
    ).model_dump(mode="json")

    ledger = build_agent_task_ledger(settings=settings, delegation_plan=delegation_plan)
    artifacts = build_delegated_artifacts(ledger=ledger, delegation_plan=delegation_plan)

    assert ledger.enabled is True
    assert ledger.tasks
    assert {task.role.value for task in ledger.tasks} >= {"orchestrator", "planner", "executor"}
    assert ledger.edges
    assert len(artifacts) >= len(ledger.tasks)
    assert all(artifact.task_id for artifact in artifacts)


def test_artifact_synthesis_consumes_only_accepted_artifacts():
    settings = Settings(agent_artifact_synthesis_enabled=True)
    result = synthesize_delegated_artifacts(
        settings=settings,
        artifacts=[
            {
                "artifact_id": "artifact-1",
                "task_id": "task-1",
                "role": "executor",
                "kind": "evidence",
                "title": "Accepted evidence",
                "summary": "Use this.",
                "status": "accepted",
            },
            {
                "artifact_id": "artifact-2",
                "task_id": "task-2",
                "role": "executor",
                "kind": "evidence",
                "title": "Rejected evidence",
                "summary": "Do not use this.",
                "status": "rejected",
            },
        ],
    )

    assert result.enabled is True
    assert result.accepted_artifact_ids == ["artifact-1"]
    assert result.skipped_artifact_ids == ["artifact-2"]
    assert "Accepted evidence" in result.summary
    assert "Rejected evidence" not in result.summary


def test_critic_gate_observe_and_enforce_retry_once():
    settings = Settings(
        agent_task_ledger_enabled=True,
        agent_critic_gate_enabled=True,
        agent_critic_gate_enforce=True,
    )
    ledger = build_agent_task_ledger(
        settings=settings,
        delegation_plan={
            "tasks": [
                {
                    "task_id": "task-1-executor",
                    "role": "executor",
                    "goal": "Produce patch evidence.",
                }
            ]
        },
    )
    artifacts = [
        {
            "artifact_id": "artifact-1",
            "task_id": "task-1-executor",
            "role": "executor",
            "kind": "evidence",
            "title": "Rejected evidence",
            "status": "rejected",
        }
    ]

    verdict = evaluate_critic_gate(settings=settings, ledger=ledger, artifacts=artifacts)
    retried = apply_critic_retry_tasks(ledger=ledger, critic_gate_result=verdict)
    blocked = synthesize_delegated_artifacts(
        settings=Settings(agent_artifact_synthesis_enabled=True),
        artifacts=artifacts,
        critic_gate_result=verdict,
    )

    assert verdict.verdict == "retry"
    assert verdict.enforce is True
    assert verdict.retry_task_ids == ["task-1-executor"]
    assert any(task.task_id == "task-1-executor-retry-1" for task in retried.tasks)
    assert blocked.blocked is True
