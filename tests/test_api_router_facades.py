from __future__ import annotations

from focus_agent.api.route_utils import (
    agent_governance_operations,
    agent_governance_serializers,
    agent_team_responses,
    harness_run_helpers,
    memory_access,
    memory_responses,
)
from focus_agent.api.routers import agent_team, harness_runs, memory


def test_memory_router_private_helpers_remain_importable_facades() -> None:
    assert memory._memory_repository is memory_access._memory_repository
    assert memory._effective_user_id_filter is memory_access._effective_user_id_filter
    assert memory._get_access_checked_record is memory_access._get_access_checked_record
    assert memory._memory_record_response is memory_responses._memory_record_response
    assert memory._audit_event_response is memory_responses._audit_event_response
    assert memory._candidate_response is memory_responses._candidate_response


def test_agent_team_router_private_helpers_remain_importable_facades() -> None:
    assert agent_team._mark_deprecated_route is agent_team_responses._mark_deprecated_route
    assert agent_team._planning_metadata_payload is agent_team_responses._planning_metadata_payload
    assert agent_team._call_plan_session is agent_team_responses._call_plan_session
    assert agent_team._view_response is agent_team_responses._view_response


def test_harness_runs_private_helpers_remain_importable_facades() -> None:
    assert harness_runs._json_safe is harness_run_helpers._json_safe
    assert harness_runs._run_record_payload is harness_run_helpers._run_record_payload
    assert harness_runs._journal_method is harness_run_helpers._journal_method
    assert harness_runs._get_persisted_run is harness_run_helpers._get_persisted_run
    assert harness_runs._canonical_custom_event is harness_run_helpers._canonical_custom_event


def test_agent_governance_operations_private_helpers_remain_importable_facades() -> None:
    assert (
        agent_governance_operations._context_evidence_response
        is agent_governance_serializers._context_evidence_response
    )
    assert (
        agent_governance_operations._skill_selection_event_response
        is agent_governance_serializers._skill_selection_event_response
    )
    assert (
        agent_governance_operations._skill_preference_response
        is agent_governance_serializers._skill_preference_response
    )
    assert agent_governance_operations._message_hash is agent_governance_serializers._message_hash
