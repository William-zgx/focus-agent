from focus_agent.api.contracts import ApplyMergeDecisionRequest
from focus_agent.api.main import create_app
from focus_agent.api.schemas import BranchTreeResponse, ForkBranchRequest, ModelCatalogResponse
from focus_agent.core.branching import BranchRole, BranchStatus, BranchTreeNode


def test_branch_tree_node_shape():
    tree = BranchTreeNode(
        thread_id="main-1",
        root_thread_id="main-1",
        branch_name="main",
        branch_role=BranchRole.MAIN,
        branch_status=BranchStatus.ACTIVE,
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
            )
        ],
    )
    dumped = response.model_dump(mode="json")
    assert dumped["root"]["children"][0]["branch_id"] == "b1"
    assert dumped["root"]["children"][0]["branch_name"] == "deep-dive"
    assert dumped["archived_branches"][0]["branch_id"] == "b2"
    assert dumped["archived_branches"][0]["is_archived"] is True
    assert "conclusion_policy" not in dumped["archived_branches"][0]


def test_fork_branch_request_allows_auto_generated_names():
    payload = ForkBranchRequest(parent_thread_id="main-1")

    assert payload.branch_name is None
    assert payload.name_source is None
    assert payload.branch_role == BranchRole.EXPLORE_ALTERNATIVES


def test_model_catalog_response_shape():
    payload = ModelCatalogResponse(
        default_model="moonshot:kimi-k2.5",
        models=[
            {
                "id": "moonshot:kimi-k2.5",
                "provider": "moonshot",
                "provider_label": "Moonshot AI",
                "name": "kimi-k2.5",
                "label": "Kimi K2.5 · Moonshot AI",
                "is_default": True,
                "supports_thinking": True,
                "default_thinking_enabled": True,
            }
        ],
    )

    dumped = payload.model_dump(mode="json")

    assert dumped["default_model"] == "moonshot:kimi-k2.5"
    assert dumped["models"][0]["provider"] == "moonshot"
    assert dumped["models"][0]["name"] == "kimi-k2.5"
    assert dumped["models"][0]["supports_thinking"] is True
    assert dumped["models"][0]["default_thinking_enabled"] is True


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


def test_public_api_no_longer_exposes_skill_catalog_routes():
    app = create_app()

    route_paths = {route.path for route in app.routes}

    assert "/v1/skills" not in route_paths
    assert "/v1/skills/{skill_id}" not in route_paths
