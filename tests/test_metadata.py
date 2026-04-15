from focus_agent.config import Settings
from focus_agent.observability.tracing import build_trace_metadata, build_trace_tags
from focus_agent.core.branching import BranchMeta, BranchRole, BranchStatus


def test_trace_metadata_contains_thread_fields():
    settings = Settings()
    meta = BranchMeta(
        branch_id="b1",
        root_thread_id="root-1",
        parent_thread_id="parent-1",
        return_thread_id="parent-1",
        branch_name="test-branch",
        branch_role=BranchRole.DEEP_DIVE,
        branch_status=BranchStatus.ACTIVE,
    )
    payload = build_trace_metadata(
        settings=settings,
        thread_id="thread-1",
        user_id="user-1",
        root_thread_id="root-1",
        branch_meta=meta,
    )
    assert payload["thread_id"] == "thread-1"
    assert payload["root_thread_id"] == "root-1"
    assert payload["branch_id"] == "b1"
    assert payload["branch_role"] == "deep_dive"


def test_trace_tags_include_root_and_thread():
    tags = build_trace_tags(root_thread_id="root-1", thread_id="thread-1")
    assert "root:root-1" in tags
    assert "thread:thread-1" in tags

def test_trace_tags_include_branch_status():
    tags = build_trace_tags(
        root_thread_id="root-1",
        thread_id="thread-1",
        branch_meta=BranchMeta(
            branch_id="b2",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            return_thread_id="root-1",
            branch_name="branch",
            branch_role=BranchRole.VERIFY,
            branch_status=BranchStatus.ACTIVE,
        ),
    )

    assert "status:active" in tags
