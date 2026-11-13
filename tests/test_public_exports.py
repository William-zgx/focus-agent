from focus_agent import (
    AppRuntime,
    BranchService,
    ChatService,
    RequestContext,
    Settings,
    create_runtime,
)
from focus_agent.api import app, create_app
from focus_agent.engine.runtime import AppRuntime as CanonicalAppRuntime
from focus_agent.engine.runtime import create_runtime as canonical_create_runtime
from focus_agent.runtime import AppRuntime as LegacyAppRuntime
from focus_agent.runtime import create_runtime as legacy_create_runtime
from focus_agent.services.branches import BranchService as CanonicalBranchService
from focus_agent.services.chat import ChatService as CanonicalChatService


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


def test_runtime_shim_remains_stable_public_facade():
    assert LegacyAppRuntime is CanonicalAppRuntime
    assert legacy_create_runtime is canonical_create_runtime
