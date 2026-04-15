from focus_agent import AppRuntime, BranchService, ChatService, RequestContext, Settings, create_runtime
from focus_agent.api import app, create_app
from focus_agent.api.contracts import ChatTurnRequest
from focus_agent.api.schemas import ChatTurnRequest as LegacyChatTurnRequest
from focus_agent.branch_service import BranchService as LegacyBranchService
from focus_agent.chat_service import ChatService as LegacyChatService
from focus_agent.engine.runtime import AppRuntime as CanonicalAppRuntime
from focus_agent.services.branches import BranchService as CanonicalBranchService
from focus_agent.services.chat import ChatService as CanonicalChatService


def test_top_level_package_exports_canonical_runtime_and_services():
    assert AppRuntime is CanonicalAppRuntime
    assert BranchService is CanonicalBranchService
    assert ChatService is CanonicalChatService
    assert create_runtime is not None
    assert Settings is not None
    assert RequestContext is not None


def test_api_package_exports_app_factory():
    assert app is not None
    assert create_app is not None


def test_legacy_shims_still_point_to_canonical_types():
    assert LegacyBranchService is CanonicalBranchService
    assert LegacyChatService is CanonicalChatService
    assert LegacyChatTurnRequest is ChatTurnRequest
