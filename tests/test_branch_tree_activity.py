from __future__ import annotations

from types import SimpleNamespace

from focus_agent.api.contract_models.branch import BranchTreeNodeView, BranchTreeResponse
from focus_agent.core.branching import BranchRole, BranchStatus, BranchTreeNode
from focus_agent.services.branches.tree import thread_last_activity_at


class _Checkpointer:
    def __init__(self, timestamps: dict[str, str]):
        self.timestamps = timestamps

    def get_tuple(self, config):
        thread_id = config["configurable"]["thread_id"]
        if thread_id not in self.timestamps:
            return None
        return SimpleNamespace(checkpoint={"ts": self.timestamps[thread_id]})


def test_thread_last_activity_reads_latest_checkpoint_ts():
    graph = SimpleNamespace(
        checkpointer=_Checkpointer({"root": "2026-10-01T10:00:00+00:00"}),
    )

    activity = thread_last_activity_at(graph, ["root", "missing", "root"])

    assert activity == {"root": "2026-10-01T10:00:00+00:00"}


def test_thread_last_activity_falls_back_to_state_snapshot_created_at():
    class _Graph:
        def get_state(self, config):
            thread_id = config["configurable"]["thread_id"]
            if thread_id == "broken":
                raise RuntimeError("boom")
            return SimpleNamespace(values={}, created_at=f"2026-10-02T00:00:00+00:00#{thread_id}")

    activity = thread_last_activity_at(_Graph(), ["child", "broken"])

    assert activity == {"child": "2026-10-02T00:00:00+00:00#child"}
    assert thread_last_activity_at(None, ["child"]) == {}


def test_branch_tree_node_view_adds_activity_recursively():
    tree = BranchTreeNode(
        thread_id="root",
        root_thread_id="root",
        children=[
            BranchTreeNode(
                thread_id="child",
                root_thread_id="root",
                parent_thread_id="root",
                branch_id="b-1",
                branch_name="Child",
                branch_role=BranchRole.DEEP_DIVE,
                branch_status=BranchStatus.AWAITING_MERGE_REVIEW,
                branch_depth=1,
                token_usage={"total_tokens": 12},
            )
        ],
    )

    view = BranchTreeNodeView.from_node(
        tree, activity_by_thread={"child": "2026-10-03T08:00:00+00:00"}
    )
    payload = BranchTreeResponse(root=view).model_dump(mode="json")

    assert payload["root"]["last_activity_at"] is None
    child = payload["root"]["children"][0]
    assert child["last_activity_at"] == "2026-10-03T08:00:00+00:00"
    assert child["branch_status"] == "awaiting_merge_review"
    assert child["token_usage"] == {"total_tokens": 12}
