from focus_agent import AppRuntime, BranchService, ChatService, RequestContext, Settings, create_runtime
from focus_agent.api import app, create_app
from focus_agent.api.contracts import ChatTurnRequest
from focus_agent.api.schemas import ChatTurnRequest as LegacyChatTurnRequest
from focus_agent.branch_service import BranchService as LegacyBranchService
from focus_agent.chat_service import ChatService as LegacyChatService
from focus_agent.core.branching import (
    BranchMeta,
    BranchRecord,
    BranchRole,
    BranchStatus,
    BranchTreeNode,
    ImportedConclusion,
    MergeDecision,
    MergeMode,
    MergeProposal,
)
from focus_agent.core.state import AgentState, initial_agent_state, normalize_agent_state, serialize_agent_state
from focus_agent.engine.graph_builder import build_graph as CanonicalBuildGraph
from focus_agent.engine.runtime import AppRuntime as CanonicalAppRuntime
from focus_agent.engine.runtime import create_runtime as canonical_create_runtime
from focus_agent.graph import build_graph as LegacyBuildGraph
from focus_agent.runtime import AppRuntime as LegacyAppRuntime
from focus_agent.runtime import create_runtime as legacy_create_runtime
from focus_agent.schemas import BranchMeta as LegacyBranchMeta
from focus_agent.schemas import BranchRecord as LegacyBranchRecord
from focus_agent.schemas import BranchRole as LegacyBranchRole
from focus_agent.schemas import BranchStatus as LegacyBranchStatus
from focus_agent.schemas import BranchTreeNode as LegacyBranchTreeNode
from focus_agent.schemas import ImportedConclusion as LegacyImportedConclusion
from focus_agent.schemas import MergeDecision as LegacyMergeDecision
from focus_agent.schemas import MergeMode as LegacyMergeMode
from focus_agent.schemas import MergeProposal as LegacyMergeProposal
from focus_agent.services.branches import BranchService as CanonicalBranchService
from focus_agent.services.chat import ChatService as CanonicalChatService
from focus_agent.state import AgentState as LegacyAgentState
from focus_agent.state import initial_agent_state as legacy_initial_agent_state
from focus_agent.state import normalize_agent_state as legacy_normalize_agent_state
from focus_agent.state import serialize_agent_state as legacy_serialize_agent_state


def test_top_level_package_exports_canonical_runtime_and_services():
    assert AppRuntime is CanonicalAppRuntime
    assert BranchService is CanonicalBranchService
    assert ChatService is CanonicalChatService
    assert create_runtime is canonical_create_runtime
    assert Settings is not None
    assert RequestContext is not None


def test_api_package_exports_app_factory():
    assert app is not None
    assert create_app is not None


def test_service_and_runtime_shims_remain_stable_public_facades():
    assert LegacyBranchService is CanonicalBranchService
    assert LegacyChatService is CanonicalChatService
    assert LegacyAppRuntime is CanonicalAppRuntime
    assert legacy_create_runtime is canonical_create_runtime
    assert LegacyBuildGraph is CanonicalBuildGraph


def test_schema_and_state_shims_remain_stable_public_facades():
    assert LegacyBranchMeta is BranchMeta
    assert LegacyBranchRecord is BranchRecord
    assert LegacyBranchRole is BranchRole
    assert LegacyBranchStatus is BranchStatus
    assert LegacyBranchTreeNode is BranchTreeNode
    assert LegacyImportedConclusion is ImportedConclusion
    assert LegacyMergeDecision is MergeDecision
    assert LegacyMergeMode is MergeMode
    assert LegacyMergeProposal is MergeProposal
    assert LegacyAgentState is AgentState
    assert legacy_initial_agent_state is initial_agent_state
    assert legacy_normalize_agent_state is normalize_agent_state
    assert legacy_serialize_agent_state is serialize_agent_state


def test_api_schema_compat_shim_still_points_to_contracts():
    assert LegacyChatTurnRequest is ChatTurnRequest
