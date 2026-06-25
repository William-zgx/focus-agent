from __future__ import annotations

import json
from types import SimpleNamespace

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.core.governance import (
    BranchDecisionAction,
    BranchDecisionEvent,
    BranchDecisionStatus,
    ContextMemoryEvidence,
    FeedbackEvent,
    SkillSelectionEvent,
)
from focus_agent.retrieval import InMemoryRetrievalIndex
from focus_agent.retrieval.agent_team import (
    AgentTeamPlanRetrievalService,
    index_agent_team_plan,
)
from focus_agent.retrieval.branch_context import (
    BranchContextRetrievalService,
    index_branch_decision_event,
)
from focus_agent.retrieval.failure_cases import (
    FailureCaseRetrievalService,
    index_failure_case_from_trajectory,
)
from focus_agent.retrieval.governance_feedback import (
    GovernanceFeedbackRetrievalService,
    index_governance_feedback,
)
from focus_agent.retrieval.workspace import (
    WorkspaceSemanticSearchService,
    index_workspace,
)
from focus_agent.retrieval_index_cli import build_parser


class _FakeEmbeddingProvider:
    provider_id = "fake"
    model_id = "fake"
    dimensions = 3

    def embed(self, texts):
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    1.0 if "branch" in lowered or "分支" in lowered else 0.0,
                    1.0 if "failure" in lowered or "error" in lowered else 0.0,
                    1.0 if "workspace" in lowered or "code" in lowered else 0.0,
                ]
            )
        return vectors


def _session() -> AgentTeamSession:
    return AgentTeamSession(
        session_id="session-1",
        root_thread_id="root-1",
        user_id="user-1",
        title="Zvec migration",
        goal="Plan Zvec retrieval migration",
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )


def _task() -> AgentTeamTask:
    return AgentTeamTask(
        task_id="task-1",
        session_id="session-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        title="Implement retrieval",
        goal="Implement Zvec retrieval index",
        status=AgentTeamTaskStatus.DONE,
        acceptance_criteria=["retrieval tests pass"],
        context_refs=[{"kind": "memory", "id": "memory-1"}],
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )


def _output() -> AgentTeamTaskOutput:
    return AgentTeamTaskOutput(
        output_id="output-1",
        task_id="task-1",
        kind=AgentTeamArtifactKind.HANDOFF,
        summary="Implemented retrieval with fallback.",
        created_at="2026-06-25T00:00:00+00:00",
    )


def test_branch_context_indexes_and_hydrates_canonical_event():
    index = InMemoryRetrievalIndex()
    provider = _FakeEmbeddingProvider()
    event = BranchDecisionEvent(
        decision_id="decision-1",
        user_id="user-1",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        branch_id="branch-1",
        action=BranchDecisionAction.FORK_CHILD_BRANCH,
        status=BranchDecisionStatus.SHADOWED,
        rationale="branch topic drift",
        metadata={"handoff_message": "研究另一个分支方案"},
    )
    repo = SimpleNamespace(get_branch_decision_event=lambda decision_id: event)

    index_branch_decision_event(
        retrieval_index=index,
        embedding_provider=provider,
        event=event,
    )
    hits = BranchContextRetrievalService(
        retrieval_index=index,
        embedding_provider=provider,
        repository=repo,
    ).search_similar_context(
        query="分支方案",
        user_id="user-1",
        root_thread_id="root-1",
        limit=3,
    )

    assert [hit.source_id for hit in hits] == ["decision-1"]
    assert hits[0].fields["status"] == "shadowed"


def test_agent_team_plan_search_returns_context_refs_from_same_user_root():
    index = InMemoryRetrievalIndex()
    provider = _FakeEmbeddingProvider()
    session = _session()
    task = _task()
    output = _output()
    repo = SimpleNamespace(
        get_session=lambda session_id: session,
        list_tasks=lambda session_id: [task],
        list_task_outputs=lambda task_id: [output],
    )

    index_agent_team_plan(
        retrieval_index=index,
        embedding_provider=provider,
        session=session,
        tasks=[task],
        outputs=[output],
    )
    hits = AgentTeamPlanRetrievalService(
        retrieval_index=index,
        embedding_provider=provider,
        repository=repo,
    ).search_similar_plans(
        query="Zvec retrieval migration",
        user_id="user-1",
        root_thread_id="root-1",
        limit=3,
    )

    assert hits[0].source_id == "session-1"
    assert hits[0].context_refs == [{"kind": "memory", "id": "memory-1"}]


def test_failure_case_retrieval_filters_by_workspace_and_root():
    index = InMemoryRetrievalIndex()
    provider = _FakeEmbeddingProvider()
    record = SimpleNamespace(
        id="turn-1",
        root_thread_id="root-1",
        thread_id="thread-1",
        status="failed",
        task_brief="Fix workspace code failure",
        error="Tool failure",
        plan_meta={"workspace_root": "/repo"},
        trajectory=[
            SimpleNamespace(tool="run_tests", args={}, observation="", error="pytest failed")
        ],
    )

    index_failure_case_from_trajectory(
        retrieval_index=index,
        embedding_provider=provider,
        record=record,
    )
    hits = FailureCaseRetrievalService(
        retrieval_index=index,
        embedding_provider=provider,
    ).search_recovery_cases(
        query="workspace failure",
        root_thread_id="root-1",
        workspace_root="/repo",
        limit=5,
    )

    assert [hit.source_id for hit in hits] == ["turn-1"]
    assert hits[0].fields["status"] == "failed"


def test_governance_feedback_indexes_negative_skill_feedback():
    index = InMemoryRetrievalIndex()
    provider = _FakeEmbeddingProvider()
    event = SkillSelectionEvent(
        selection_id="selection-1",
        user_id="user-1",
        message_preview="Use retrieval skill",
        activated_skill_ids=["retrieval"],
        feedback="negative",
        feedback_reason="wrong skill",
    )

    index_governance_feedback(
        retrieval_index=index,
        embedding_provider=provider,
        item=event,
    )
    hits = GovernanceFeedbackRetrievalService(
        retrieval_index=index,
        embedding_provider=provider,
    ).search_feedback(query="retrieval skill", user_id="user-1", limit=5)

    assert hits[0].source_id == "selection-1"
    assert hits[0].fields["feedback"] == "negative"


def test_governance_feedback_indexes_context_and_feedback_events():
    index = InMemoryRetrievalIndex()
    provider = _FakeEmbeddingProvider()
    context = ContextMemoryEvidence(
        evidence_id="ctx-1",
        user_id="user-1",
        thread_id="thread-1",
        selected_memories=[{"memory_id": "memory-1", "summary": "retrieval"}],
        drift_report={"drift_risk": "high"},
    )
    feedback = FeedbackEvent(
        event_id="feedback-1",
        user_id="user-1",
        source_kind="answer",
        source_id="turn-1",
        sentiment="negative",
        category="retrieval",
        metadata={"reason": "missing context"},
    )

    index_governance_feedback(
        retrieval_index=index,
        embedding_provider=provider,
        item=context,
    )
    index_governance_feedback(
        retrieval_index=index,
        embedding_provider=provider,
        item=feedback,
    )
    hits = GovernanceFeedbackRetrievalService(
        retrieval_index=index,
        embedding_provider=provider,
    ).search_feedback(query="retrieval missing context", user_id="user-1", limit=5)

    assert {hit.source_id for hit in hits} == {"ctx-1", "feedback-1"}


def test_workspace_semantic_search_stays_inside_root_and_filters_stale_files(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    code = workspace / "src" / "retrieval.py"
    code.parent.mkdir()
    code.write_text("def zvec_workspace_search():\n    return 'workspace code'\n", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "ignored.py").write_text("workspace hidden\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("workspace outside\n", encoding="utf-8")
    index = InMemoryRetrievalIndex()
    provider = _FakeEmbeddingProvider()

    summary = index_workspace(
        retrieval_index=index,
        embedding_provider=provider,
        workspace_root=workspace,
    )
    code.write_text("def changed():\n    return 'new content'\n", encoding="utf-8")
    hits = WorkspaceSemanticSearchService(
        retrieval_index=index,
        embedding_provider=provider,
        workspace_root=workspace,
    ).search_workspace(query="workspace code", limit=5)

    assert summary["indexed_files"] == 1
    assert hits == []
    assert not any("ignored.py" in json.dumps(hit.fields) for hit in hits)
    assert not any(str(outside) in json.dumps(hit.fields) for hit in hits)


def test_retrieval_cli_accepts_expanded_backfill_targets():
    parser = build_parser()

    args = parser.parse_args(["backfill", "--target", "workspace", "--limit", "10"])

    assert args.command == "backfill"
    assert args.target == "workspace"
    assert args.limit == 10
