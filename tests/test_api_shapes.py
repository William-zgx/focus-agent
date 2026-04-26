from focus_agent.api.contracts import ApplyMergeDecisionRequest
from focus_agent.api.main import _aggregate_token_usage_from_turns, _annotate_branch_tree_token_usage, create_app
from focus_agent.api.schemas import (
    AgentRoleDecisionListResponse,
    AgentRoleDryRunRequest,
    AgentRoleDryRunResponse,
    AgentRolePolicyResponse,
    AgentDelegationPlanRequest,
    AgentDelegationPlanResponse,
    AgentDelegationPolicyResponse,
    AgentDelegationRunListResponse,
    AgentModelRouteRequest,
    AgentModelRouteResponse,
    AgentModelRouterDecisionListResponse,
    AgentModelRouterPolicyResponse,
    AgentReviewQueueDecisionResponse,
    AgentReviewQueueListResponse,
    AgentContextArtifactListResponse,
    AgentContextDecisionListResponse,
    AgentContextPolicyResponse,
    AgentContextPreviewRequest,
    AgentContextPreviewResponse,
    AgentArtifactListResponse,
    AgentArtifactSynthesisRequest,
    AgentArtifactSynthesisResponse,
    AgentCriticEvaluateRequest,
    AgentCriticEvaluateResponse,
    AgentCriticVerdictListResponse,
    AgentTaskLedgerPlanRequest,
    AgentTaskLedgerPlanResponse,
    AgentTaskLedgerPolicyResponse,
    AgentTaskLedgerRunListResponse,
    AgentSelfRepairFailureListResponse,
    AgentSelfRepairPromotePreviewRequest,
    AgentSelfRepairPromotePreviewResponse,
    BranchActionExecuteResponse,
    BranchActionNavigation,
    BranchActionProposal,
    BranchTreeResponse,
    ContextUsageResponse,
    ConversationListResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    ForkBranchRequest,
    ModelCatalogResponse,
    TrajectoryBatchPromotionPreviewRequest,
    TrajectoryBatchPromotionPreviewResponse,
    TrajectoryBatchReplayCompareRequest,
    TrajectoryBatchReplayCompareResponse,
    TrajectoryPromotionResponse,
    TrajectoryPromotionRequest,
    TrajectoryReplayResponse,
    TrajectoryReplayRequest,
    TrajectoryTurnListResponse,
    TrajectoryTurnStatsEnvelopeResponse,
    ThreadContextCompactRequest,
    ThreadContextPreviewRequest,
    ThreadContextPreviewResponse,
    ThreadStateResponse,
    UpdateBranchNameRequest,
    UpdateConversationRequest,
)
from focus_agent.core.branching import BranchActionKind, BranchActionStatus, BranchRole, BranchStatus, BranchTreeNode


def test_branch_tree_node_shape():
    tree = BranchTreeNode(
        thread_id="main-1",
        root_thread_id="main-1",
        branch_name="main",
        branch_role=BranchRole.MAIN,
        branch_status=BranchStatus.ACTIVE,
        token_usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        children=[
            BranchTreeNode(
                thread_id="child-1",
                root_thread_id="main-1",
                parent_thread_id="main-1",
                branch_id="b1",
                branch_name="deep-dive",
                branch_role=BranchRole.DEEP_DIVE,
                branch_status=BranchStatus.ACTIVE,
                branch_depth=1,
                token_usage={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
            )
        ],
    )
    response = BranchTreeResponse(
        root=tree,
        archived_branches=[
            BranchTreeNode(
                thread_id="archived-1",
                root_thread_id="main-1",
                parent_thread_id="main-1",
                branch_id="b2",
                branch_name="archived",
                branch_role=BranchRole.VERIFY,
                branch_status=BranchStatus.PAUSED,
                is_archived=True,
                archived_at="2026-04-12 10:00:00",
                branch_depth=1,
                token_usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            )
        ],
    )
    dumped = response.model_dump(mode="json")
    assert dumped["root"]["children"][0]["branch_id"] == "b1"
    assert dumped["root"]["children"][0]["branch_name"] == "deep-dive"
    assert dumped["archived_branches"][0]["branch_id"] == "b2"
    assert dumped["archived_branches"][0]["is_archived"] is True
    assert dumped["root"]["token_usage"]["total_tokens"] == 15
    assert dumped["archived_branches"][0]["token_usage"]["total_tokens"] == 6
    assert "conclusion_policy" not in dumped["archived_branches"][0]


def test_fork_branch_request_allows_auto_generated_names():
    payload = ForkBranchRequest(parent_thread_id="main-1")

    assert payload.branch_name is None
    assert payload.name_source is None
    assert payload.language is None
    assert payload.branch_role == BranchRole.EXPLORE_ALTERNATIVES


def test_model_catalog_response_shape():
    payload = ModelCatalogResponse(
        default_model="moonshot:kimi-k2.6",
        models=[
            {
                "id": "moonshot:kimi-k2.6",
                "provider": "moonshot",
                "provider_label": "Moonshot AI",
                "name": "kimi-k2.6",
                "label": "Kimi K2.6 · Moonshot AI",
                "is_default": True,
                "supports_thinking": True,
                "default_thinking_enabled": True,
            }
        ],
    )

    dumped = payload.model_dump(mode="json")

    assert dumped["default_model"] == "moonshot:kimi-k2.6"
    assert dumped["models"][0]["provider"] == "moonshot"
    assert dumped["models"][0]["name"] == "kimi-k2.6"
    assert dumped["models"][0]["supports_thinking"] is True
    assert dumped["models"][0]["default_thinking_enabled"] is True


def test_thread_context_usage_contract_shape_is_separate_from_token_usage():
    usage = ContextUsageResponse(
        used_tokens=104000,
        token_limit=258000,
        remaining_tokens=154000,
        used_ratio=0.4,
        status="ok",
        prompt_chars=416000,
        prompt_budget_chars=1032000,
        tokenizer_mode="chars_fallback",
        last_compacted_at="2026-04-26T10:00:00+00:00",
    )
    thread = ThreadStateResponse(
        thread_id="thread-1",
        root_thread_id="thread-1",
        context_usage=usage,
        messages=[
            {
                "type": "ai",
                "content": "done",
                "usage_metadata": {
                    "input_tokens": 12,
                    "output_tokens": 8,
                    "total_tokens": 20,
                },
            }
        ],
    )
    preview = ThreadContextPreviewResponse(context_usage=usage)

    dumped = thread.model_dump(mode="json")

    assert ThreadContextPreviewRequest(draft_message="hello").draft_message == "hello"
    assert ThreadContextCompactRequest(trigger="manual").trigger == "manual"
    assert preview.context_usage.used_tokens == 104000
    assert dumped["context_usage"]["used_tokens"] == 104000
    assert dumped["messages"][0]["usage_metadata"]["total_tokens"] == 20
    assert "token_usage" not in dumped["context_usage"]


def test_branch_action_contract_shapes():
    action = BranchActionProposal(
        action_id="branch-action-1",
        kind=BranchActionKind.FORK_SIBLING_BRANCH,
        status=BranchActionStatus.PENDING,
        root_thread_id="root-1",
        source_thread_id="child-1",
        target_parent_thread_id="root-1",
        suggested_branch_name="华英农业",
        branch_role=BranchRole.EXPLORE_ALTERNATIVES,
        reason="User requested branch switch.",
        created_at="2026-04-26T00:00:00+00:00",
    )
    thread = ThreadStateResponse(
        thread_id="child-1",
        root_thread_id="root-1",
        branch_actions=[action],
    )
    response = BranchActionExecuteResponse(
        thread_state=thread,
        branch_action=action.model_copy(update={"status": BranchActionStatus.EXECUTED}),
        navigation=BranchActionNavigation(root_thread_id="root-1", thread_id="child-2"),
    )

    dumped = response.model_dump(mode="json")

    assert thread.branch_actions[0].kind == BranchActionKind.FORK_SIBLING_BRANCH
    assert dumped["branch_action"]["status"] == "executed"
    assert dumped["navigation"] == {"root_thread_id": "root-1", "thread_id": "child-2"}


def test_agent_role_contract_shapes():
    policy = AgentRolePolicyResponse(
        enabled=True,
        default_model="openai:gpt-4.1-mini",
        helper_model="openai:deepseek-chat",
        max_parallel_runs=3,
        roles=["orchestrator", "planner", "executor", "critic", "memory_curator", "skill_scout"],
        role_models={"executor": "openai:gpt-4.1-mini", "critic": "openai:deepseek-chat"},
        fallback_order=["role-specific model override", "executor selected model", "helper model"],
    )
    dry_run_request = AgentRoleDryRunRequest(
        message="Plan, implement, and verify the role routing console.",
        scene="role_routing_console",
        available_tools=["search_code", "read_file"],
    )
    dry_run_response = AgentRoleDryRunResponse(
        policy=policy,
        plan={
            "enabled": True,
            "decisions": [
                {"role": "orchestrator", "model_id": "openai:deepseek-chat"},
                {"role": "executor", "model_id": "openai:gpt-4.1-mini"},
            ],
        },
    )
    decision_list = AgentRoleDecisionListResponse(
        items=[
            {
                "turn_id": "turn-1",
                "role_count": 2,
                "decisions": dry_run_response.plan["decisions"],
            }
        ],
        count=1,
        trajectory_available=True,
    )

    dumped = dry_run_response.model_dump(mode="json")

    assert policy.roles == [
        "orchestrator",
        "planner",
        "executor",
        "critic",
        "memory_curator",
        "skill_scout",
    ]
    assert dry_run_request.available_tools == ["search_code", "read_file"]
    assert dumped["plan"]["decisions"][1]["role"] == "executor"
    assert decision_list.items[0]["turn_id"] == "turn-1"
    assert decision_list.trajectory_available is True

    from focus_agent.api.contracts import (
        AgentCapabilityListResponse,
        AgentCapabilityResponse,
        AgentMemoryCuratorDecisionListResponse,
        AgentMemoryCuratorEvaluateRequest,
        AgentMemoryCuratorEvaluateResponse,
        AgentMemoryCuratorPolicyResponse,
        AgentToolRouteDecisionListResponse,
        AgentToolRouteRequest,
        AgentToolRouteResponse,
    )

    capabilities = AgentCapabilityListResponse(
        items=[
            AgentCapabilityResponse(
                name="search_code",
                description="Search code",
                toolset="workspace",
                allowed_roles=["executor", "critic"],
                parallel_safe=True,
            )
        ],
        count=1,
    )
    route_request = AgentToolRouteRequest(role="critic", available_tools=["search_code"])
    route_response = AgentToolRouteResponse(plan={"allowed_tools": ["search_code"]})
    memory_policy = AgentMemoryCuratorPolicyResponse(enabled=True)
    memory_request = AgentMemoryCuratorEvaluateRequest(
        root_thread_id="root-1",
        branch_id="branch-1",
        findings=[{"finding": "Promote me"}],
    )
    memory_response = AgentMemoryCuratorEvaluateResponse(decision={"status": "ready"})
    tool_decisions = AgentToolRouteDecisionListResponse(items=[{"turn_id": "turn-1"}], count=1)
    memory_decisions = AgentMemoryCuratorDecisionListResponse(items=[{"turn_id": "turn-1"}], count=1)

    assert capabilities.items[0].name == "search_code"
    assert route_request.role == "critic"
    assert route_response.plan["allowed_tools"] == ["search_code"]
    assert memory_policy.conflict_strategy == "needs_review"
    assert memory_request.findings[0]["finding"] == "Promote me"
    assert memory_response.decision["status"] == "ready"
    assert tool_decisions.count == 1
    assert memory_decisions.count == 1

    delegation_policy = AgentDelegationPolicyResponse(enabled=True, enforce=False, max_parallel_runs=2)
    delegation_request = AgentDelegationPlanRequest(message="Plan, execute, and verify.")
    delegation_response = AgentDelegationPlanResponse(
        policy=delegation_policy,
        plan={"enabled": True, "runs": [{"role": "executor"}]},
    )
    delegation_runs = AgentDelegationRunListResponse(items=[{"run_id": "run-1"}], count=1)
    model_policy = AgentModelRouterPolicyResponse(
        enabled=True,
        mode="observe",
        default_model="openai:gpt-4.1-mini",
        role_models={"executor": "openai:gpt-4.1-mini"},
    )
    model_request = AgentModelRouteRequest(role="critic", selected_model="openai:gpt-4.1-mini")
    model_response = AgentModelRouteResponse(decision={"effective_model": "openai:deepseek-chat"})
    model_decisions = AgentModelRouterDecisionListResponse(items=[{"turn_id": "turn-1"}], count=1)
    failures = AgentSelfRepairFailureListResponse(items=[{"failure_type": "tool_denied"}], count=1)
    promote_request = AgentSelfRepairPromotePreviewRequest(failures=[{"failure_type": "tool_denied"}])
    promote_response = AgentSelfRepairPromotePreviewResponse(preview={"candidates": []})
    review_queue = AgentReviewQueueListResponse(items=[{"item_id": "review-1"}], count=1)
    review_response = AgentReviewQueueDecisionResponse(item={"item_id": "review-1", "status": "approved"})
    context_policy = AgentContextPolicyResponse(enabled=True, artifact_min_chars=12000)
    context_preview_request = AgentContextPreviewRequest(
        state={"context_budget": {"prompt_token_limit": 1200}},
        assembled_context="long context",
    )
    context_preview = AgentContextPreviewResponse(decision={"budget": {"prompt_chars": 12}})
    context_decisions = AgentContextDecisionListResponse(items=[{"prompt_chars": 12}], count=1)
    context_artifacts = AgentContextArtifactListResponse(items=[{"artifact_id": "context/a.txt"}], count=1)
    task_ledger_policy = AgentTaskLedgerPolicyResponse(enabled=True, artifact_synthesis_enabled=True)
    task_ledger_request = AgentTaskLedgerPlanRequest(message="Plan tasks")
    task_ledger_response = AgentTaskLedgerPlanResponse(
        policy=task_ledger_policy,
        ledger={"tasks": [{"task_id": "task-1"}]},
        artifacts=[{"artifact_id": "artifact-1"}],
    )
    task_ledger_runs = AgentTaskLedgerRunListResponse(items=[{"task_id": "task-1"}], count=1)
    artifact_list = AgentArtifactListResponse(items=[{"artifact_id": "artifact-1"}], count=1)
    synthesis_request = AgentArtifactSynthesisRequest(artifacts=[{"artifact_id": "artifact-1"}])
    synthesis_response = AgentArtifactSynthesisResponse(result={"accepted_artifact_ids": ["artifact-1"]})
    critic_verdicts = AgentCriticVerdictListResponse(items=[{"verdict": "pass"}], count=1)
    critic_request = AgentCriticEvaluateRequest(artifacts=[{"artifact_id": "artifact-1"}])
    critic_response = AgentCriticEvaluateResponse(result={"verdict": "pass"})

    assert delegation_request.scene == "agent_delegation_console"
    assert delegation_response.plan["runs"][0]["role"] == "executor"
    assert delegation_runs.items[0]["run_id"] == "run-1"
    assert model_policy.role_models["executor"] == "openai:gpt-4.1-mini"
    assert model_request.role == "critic"
    assert model_response.decision["effective_model"] == "openai:deepseek-chat"
    assert model_decisions.count == 1
    assert failures.items[0]["failure_type"] == "tool_denied"
    assert promote_request.case_id_prefix == "agent_delegation"
    assert promote_response.preview["candidates"] == []
    assert review_queue.items[0]["item_id"] == "review-1"
    assert review_response.item["status"] == "approved"
    assert context_policy.tokenizer_mode == "chars_fallback"
    assert context_preview_request.prompt_mode == "explore"
    assert context_preview.decision["budget"]["prompt_chars"] == 12
    assert context_decisions.count == 1
    assert context_artifacts.items[0]["artifact_id"] == "context/a.txt"
    assert task_ledger_policy.critic_gate_enforce is False
    assert task_ledger_request.message == "Plan tasks"
    assert task_ledger_response.ledger["tasks"][0]["task_id"] == "task-1"
    assert task_ledger_runs.count == 1
    assert artifact_list.items[0]["artifact_id"] == "artifact-1"
    assert synthesis_request.artifacts[0]["artifact_id"] == "artifact-1"
    assert synthesis_response.result["accepted_artifact_ids"] == ["artifact-1"]
    assert critic_verdicts.items[0]["verdict"] == "pass"
    assert critic_request.ledger == {}
    assert critic_response.result["verdict"] == "pass"


def test_conversation_contract_shapes():
    created = ConversationSummaryResponse(
        root_thread_id="root-1",
        title="Conversation 1",
        is_archived=False,
        created_at="2026-04-17 10:00:00",
        updated_at="2026-04-17 10:05:00",
        token_usage={"input_tokens": 20, "output_tokens": 12, "total_tokens": 32},
    )
    listing = ConversationListResponse(conversations=[created])
    request = CreateConversationRequest()
    update = UpdateConversationRequest(title="Renamed")
    rename_branch = UpdateBranchNameRequest(branch_name="Renamed node")

    dumped = listing.model_dump(mode="json")

    assert dumped["conversations"][0]["root_thread_id"] == "root-1"
    assert dumped["conversations"][0]["title"] == "Conversation 1"
    assert dumped["conversations"][0]["is_archived"] is False
    assert dumped["conversations"][0]["token_usage"]["total_tokens"] == 32
    assert request.title is None
    assert update.title == "Renamed"
    assert rename_branch.branch_name == "Renamed node"


def test_api_token_usage_helpers_aggregate_and_annotate_tree():
    total = _aggregate_token_usage_from_turns(
        [
            {"metrics": {"input_tokens": 12, "output_tokens": 8}},
            {"metrics": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12}},
        ]
    )
    annotated = _annotate_branch_tree_token_usage(
        BranchTreeNode(
            thread_id="root-1",
            root_thread_id="root-1",
            branch_name="main",
            branch_role=BranchRole.MAIN,
            branch_status=BranchStatus.ACTIVE,
            children=[],
        ),
        by_thread_id={"root-1": total},
    )

    assert total == {"input_tokens": 17, "output_tokens": 15, "total_tokens": 32}
    assert annotated.token_usage["total_tokens"] == 32


def test_apply_merge_decision_request_allows_proposal_overrides():
    payload = ApplyMergeDecisionRequest.model_validate(
        {
            "approved": True,
            "mode": "summary_plus_evidence",
            "proposal_overrides": {
                "summary": "Edited summary",
                "key_findings": ["Finding A"],
            },
        }
    )

    dumped = payload.model_dump(mode="json")

    assert dumped["proposal_overrides"]["summary"] == "Edited summary"
    assert dumped["proposal_overrides"]["key_findings"] == ["Finding A"]


def test_trajectory_contract_shapes():
    listing = TrajectoryTurnListResponse(limit=20, offset=0, count=1, filters={"status": ["failed"]})
    stats = TrajectoryTurnStatsEnvelopeResponse(filters={"fallback_used": True})
    replay = TrajectoryReplayRequest(copy_tool_trajectory=True)
    promote = TrajectoryPromotionRequest(copy_answer_substring=True)
    batch_promote = TrajectoryBatchPromotionPreviewRequest(status=["failed"], limit=5)
    batch_replay = TrajectoryBatchReplayCompareRequest(model="moonshot:kimi-k2.6", turn_ids=["turn-1"])
    replay_response = TrajectoryReplayResponse(
        source_turn_id="turn-1",
        model_used="openai:gpt-4.1-mini",
        replay_case={
            "id": "traj-turn-1",
            "scene": "long_dialog_research",
            "input": {"user_message": "Read README"},
            "expected": {},
        },
        replay_case_jsonl='{"id":"traj-turn-1"}',
        replay_result={"case_id": "traj-turn-1", "passed": True, "answer": "ok"},
        comparison={"case_id": "traj-turn-1", "replay_passed": True},
    )
    promote_response = TrajectoryPromotionResponse(
        source_turn_id="turn-1",
        case_id="traj-turn-1",
        dataset_record={
            "id": "traj-turn-1",
            "scene": "long_dialog_research",
            "input": {"user_message": "Read README"},
            "expected": {},
        },
        jsonl='{"id":"traj-turn-1"}',
    )
    batch_promote_response = TrajectoryBatchPromotionPreviewResponse(
        items=[promote_response],
        count=1,
        filters={"status": ["failed"]},
        limit=5,
        offset=0,
        jsonl='{"id":"traj-turn-1"}',
    )
    batch_replay_response = TrajectoryBatchReplayCompareResponse(
        results=[replay_response],
        summary={"total": 1, "passed": 1, "failed": 0, "source_failed": 1, "tool_path_changed": 0},
        filters={"turn_ids": ["turn-1"]},
        limit=5,
        offset=0,
    )

    assert listing.model_dump(mode="json")["count"] == 1
    assert listing.model_dump(mode="json")["filters"]["status"] == ["failed"]
    assert stats.model_dump(mode="json")["filters"]["fallback_used"] is True
    assert replay.copy_tool_trajectory is True
    assert promote.copy_answer_substring is True
    assert batch_promote.status == ["failed"]
    assert batch_promote.limit == 5
    assert batch_replay.model == "moonshot:kimi-k2.6"
    assert replay_response.model_dump(mode="json")["replay_case"]["input"]["user_message"] == "Read README"
    assert replay_response.model_dump(mode="json")["comparison"]["replay_passed"] is True
    assert promote_response.model_dump(mode="json")["dataset_record"]["id"] == "traj-turn-1"
    assert batch_promote_response.model_dump(mode="json")["jsonl"] == '{"id":"traj-turn-1"}'
    assert batch_replay_response.model_dump(mode="json")["summary"]["source_failed"] == 1


def test_public_api_no_longer_exposes_skill_catalog_routes():
    app = create_app()

    route_paths = {route.path for route in app.routes}

    assert "/v1/conversations" in route_paths
    assert "/v1/conversations/{root_thread_id}" in route_paths
    assert "/v1/conversations/{root_thread_id}/archive" in route_paths
    assert "/v1/conversations/{root_thread_id}/activate" in route_paths
    assert "/readyz" in route_paths
    assert "/metrics" in route_paths
    assert "/v1/agent/roles/policy" in route_paths
    assert "/v1/agent/roles/dry-run" in route_paths
    assert "/v1/agent/roles/decisions" in route_paths
    assert "/v1/agent/capabilities" in route_paths
    assert "/v1/agent/tool-router/route" in route_paths
    assert "/v1/agent/tool-router/decisions" in route_paths
    assert "/v1/agent/memory/curator/policy" in route_paths
    assert "/v1/agent/memory/curator/evaluate" in route_paths
    assert "/v1/agent/memory/curator/decisions" in route_paths
    assert "/v1/agent/delegation/policy" in route_paths
    assert "/v1/agent/delegation/plan" in route_paths
    assert "/v1/agent/delegation/runs" in route_paths
    assert "/v1/agent/model-router/policy" in route_paths
    assert "/v1/agent/model-router/route" in route_paths
    assert "/v1/agent/model-router/decisions" in route_paths
    assert "/v1/agent/self-repair/failures" in route_paths
    assert "/v1/agent/self-repair/promote-preview" in route_paths
    assert "/v1/agent/review-queue" in route_paths
    assert "/v1/agent/review-queue/{item_id}/approve" in route_paths
    assert "/v1/agent/review-queue/{item_id}/reject" in route_paths
    assert "/v1/observability/overview" in route_paths
    assert "/v1/observability/trajectory" in route_paths
    assert "/v1/observability/trajectory/stats" in route_paths
    assert "/v1/observability/trajectory/{turn_id}" in route_paths
    assert "/v1/observability/trajectory/{turn_id}/replay" in route_paths
    assert "/v1/observability/trajectory/{turn_id}/promote" in route_paths
    assert "/v1/observability/trajectory/batch/promote-preview" in route_paths
    assert "/v1/observability/trajectory/batch/replay-compare" in route_paths
    assert "/v1/branches/{child_thread_id}" in route_paths
    assert "/v1/skills" not in route_paths
    assert "/v1/skills/{skill_id}" not in route_paths
