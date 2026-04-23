from focus_agent.api.contracts import ApplyMergeDecisionRequest
from focus_agent.api.main import _aggregate_token_usage_from_turns, _annotate_branch_tree_token_usage, create_app
from focus_agent.api.schemas import (
    BranchTreeResponse,
    ConversationListResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    ForkBranchRequest,
    ModelCatalogResponse,
    TrajectoryPromotionResponse,
    TrajectoryPromotionRequest,
    TrajectoryReplayResponse,
    TrajectoryReplayRequest,
    TrajectoryTurnListResponse,
    TrajectoryTurnStatsEnvelopeResponse,
    UpdateBranchNameRequest,
    UpdateConversationRequest,
)
from focus_agent.core.branching import BranchRole, BranchStatus, BranchTreeNode


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

    assert listing.model_dump(mode="json")["count"] == 1
    assert listing.model_dump(mode="json")["filters"]["status"] == ["failed"]
    assert stats.model_dump(mode="json")["filters"]["fallback_used"] is True
    assert replay.copy_tool_trajectory is True
    assert promote.copy_answer_substring is True
    assert replay_response.model_dump(mode="json")["replay_case"]["input"]["user_message"] == "Read README"
    assert replay_response.model_dump(mode="json")["comparison"]["replay_passed"] is True
    assert promote_response.model_dump(mode="json")["dataset_record"]["id"] == "traj-turn-1"


def test_public_api_no_longer_exposes_skill_catalog_routes():
    app = create_app()

    route_paths = {route.path for route in app.routes}

    assert "/v1/conversations" in route_paths
    assert "/v1/conversations/{root_thread_id}" in route_paths
    assert "/v1/conversations/{root_thread_id}/archive" in route_paths
    assert "/v1/conversations/{root_thread_id}/activate" in route_paths
    assert "/readyz" in route_paths
    assert "/metrics" in route_paths
    assert "/v1/observability/overview" in route_paths
    assert "/v1/observability/trajectory" in route_paths
    assert "/v1/observability/trajectory/stats" in route_paths
    assert "/v1/observability/trajectory/{turn_id}" in route_paths
    assert "/v1/observability/trajectory/{turn_id}/replay" in route_paths
    assert "/v1/observability/trajectory/{turn_id}/promote" in route_paths
    assert "/v1/branches/{child_thread_id}" in route_paths
    assert "/v1/skills" not in route_paths
    assert "/v1/skills/{skill_id}" not in route_paths
