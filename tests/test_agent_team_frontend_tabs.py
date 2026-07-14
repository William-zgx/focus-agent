from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "apps" / "web"
APP_ROOT = WEB_ROOT / "src" / "app"
AGENT_TEAM_ROOT = WEB_ROOT / "src" / "features" / "agent-team"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_agent_team_global_navigation_is_feature_gated_and_keeps_android_hidden():
    navigation = _read(APP_ROOT / "shell" / "app-shell-global-navigation.tsx")
    env = _read(WEB_ROOT / "src" / "shared" / "config" / "env.ts")

    assert "AgentTeamIcon" in navigation
    assert "agentTeamNavLabel" in navigation
    assert "appEnv.features.agentTeam" in navigation
    assert 'to="/agent-team"' in navigation
    assert "isAgentTeamRoute" in navigation
    assert 'import.meta.env.VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH === "true"' in env
    assert "agentTeam: !isAndroidTarget && isAgentTeamEnabled" in env
    assert "agentTeam: envFlag(" not in env


def test_agent_team_routes_keep_legacy_paths_and_register_url_tabs():
    router = _read(APP_ROOT / "router.tsx")

    for path in [
        'path: "/agent-team"',
        'path: "/agent-team/$sessionId"',
        'path: "/agent-team/$sessionId/tasks"',
        'path: "/agent-team/$sessionId/approvals"',
        'path: "/agent-team/$sessionId/evidence"',
    ]:
        assert path in router

    assert "LazyAgentTeamWorkbenchPage" in router
    assert "agentTeamTasksRoute" in router
    assert "agentTeamApprovalsRoute" in router
    assert "agentTeamEvidenceRoute" in router


def test_agent_team_tabs_are_url_driven_and_lazy_loaded():
    page = _read(WEB_ROOT / "src" / "pages" / "agent-team" / "team-workbench-page.tsx")
    shell = _read(AGENT_TEAM_ROOT / "agent-team-tab-shell.tsx")
    tab_types = _read(AGENT_TEAM_ROOT / "agent-team-tab-types.ts")

    assert "agentTeamTabFromPathname(pathname)" in page
    assert 'import "@/shared/styles/modules/agent-team.css";' in page
    for tab in ["mission", "tasks", "approvals", "evidence"]:
        assert f'"{tab}"' in tab_types
    for module_name in [
        "agent-team-workbench",
        "agent-team-tasks-tab",
        "agent-team-approvals-tab",
        "agent-team-evidence-tab",
    ]:
        assert f'import("./{module_name}")' in shell
    assert "<Suspense" in shell
    assert 'to="/agent-team/$sessionId"' in shell
    assert 'to="/agent-team/$sessionId/tasks"' in shell
    assert 'to="/agent-team/$sessionId/approvals"' in shell
    assert 'to="/agent-team/$sessionId/evidence"' in shell


def test_agent_team_queries_only_mount_on_active_team_tab_and_stop_when_leaving():
    hooks = _read(AGENT_TEAM_ROOT / "use-agent-team.ts")
    v2_hooks = _read(AGENT_TEAM_ROOT / "use-agent-team-v2.ts")
    mission = _read(AGENT_TEAM_ROOT / "agent-team-workbench.tsx")
    approvals = _read(AGENT_TEAM_ROOT / "agent-team-approvals-tab.tsx")
    evidence = _read(AGENT_TEAM_ROOT / "agent-team-evidence-tab.tsx")

    assert (
        "export function useAgentTeamSession(\n"
        "\tsessionId: string | null,\n"
        "\t{ enabled = true }: { enabled?: boolean } = {},"
    ) in hooks
    assert "useAgentTeamSession(sessionId, sessionId)" not in hooks
    assert "{ enabled = true }: { enabled?: boolean } = {}" in hooks
    assert "enabled: enabled && ready && Boolean(sessionId)" in hooks
    assert "refetchInterval: (query)" in hooks
    assert "useAgentTeamToolApprovals" not in mission
    assert "AgentTeamAdoptionWorkbench" not in mission
    assert "useAgentTeamToolApprovals(sessionId)" in approvals
    assert "AgentTeamAdoptionWorkbench" in evidence
    assert 'from "./use-agent-team-v2"' in hooks
    assert "useAgentTeamReadiness" in v2_hooks
    assert "useAgentTeamEvidence" in v2_hooks
    assert "enabled: canQuery" in v2_hooks
    assert "refetchInterval: poll ? 1500 : false" in v2_hooks
    assert "useAgentTeamEvidence(sessionId" in evidence
    assert "poll: shouldPollEvidence(view)" in evidence
    assert "useAgentTeamReadiness" in evidence


def test_chat_entry_does_not_eagerly_import_agent_team_css():
    app_styles = _read(WEB_ROOT / "src" / "shared" / "styles" / "app.css")
    page = _read(WEB_ROOT / "src" / "pages" / "agent-team" / "team-workbench-page.tsx")

    assert '@import "./modules/agent-team.css";' not in app_styles
    assert 'import "@/shared/styles/app.css";' in _read(WEB_ROOT / "src" / "main.tsx")
    assert 'import "@/shared/styles/modules/agent-team.css";' in page


def test_agent_team_route_layout_is_isolated_from_chat_and_mobile_css():
    chat_messages = _read(
        WEB_ROOT / "src" / "shared" / "styles" / "modules" / "chat-01-thread-messages.css"
    )
    mobile_overrides = _read(WEB_ROOT / "src" / "shared" / "styles" / "overrides-mobile.css")
    team_styles = _read(WEB_ROOT / "src" / "shared" / "styles" / "modules" / "agent-team.css")
    team_base = _read(WEB_ROOT / "src" / "shared" / "styles" / "modules" / "agent-team-base.css")

    assert "fa-agent-team" not in chat_messages
    assert "is-agent-team-route" not in chat_messages
    assert "fa-agent-team" not in mobile_overrides
    assert "is-agent-team-route" not in mobile_overrides
    assert '@import "./agent-team-base.css";' in team_styles
    assert ".fa-chat-main-body.is-agent-team-route" in team_base
    assert ".fa-chat-main-body.is-agent-workbench-route > .fa-agent-team-layout" in team_base
    assert ".fa-chat-main-body.is-agent-team-route > .fa-agent-team-layout" in team_base
    assert "height: 100%;" in team_base
    assert "scrollbar-gutter: stable;" in team_base
    assert "@media (max-width: 760px)" in team_base
    assert "scrollbar-gutter: auto;" in team_base
