import json
import re
from pathlib import Path


def _web_styles(web_root: Path) -> str:
    styles_root = web_root / "src" / "shared" / "styles"
    parts = [(styles_root / "app.css").read_text()]
    modules_root = styles_root / "modules"
    if modules_root.exists():
        parts.extend(path.read_text() for path in sorted(modules_root.glob("*.css")))
    return "\n".join(parts)


def _join_text(*paths: Path) -> str:
    return "\n".join(path.read_text() for path in paths)


def _compact(text: str) -> str:
    return " ".join(text.split())


def _script_budget(script_text: str) -> dict[str, int]:
    budget: dict[str, int] = {}
    for key in ["maxCssBytes", "maxJsBytes", "maxCssAssetBytes", "maxJsAssetBytes"]:
        match = re.search(rf"\b{key}:\s*([0-9_]+)", script_text)
        assert match, f"missing readable bundle budget field {key}"
        budget[key] = int(match.group(1).replace("_", ""))
    return budget


def _shell_text(web_root: Path) -> str:
    shell_root = web_root / "src" / "app" / "shell"
    paths = sorted(shell_root.glob("*.tsx")) + sorted((shell_root / "hooks").glob("*.ts"))
    paths.append(shell_root / "app-shell-config.ts")
    return _join_text(*paths)


def test_web_bundle_budget_check_is_wired_and_readable():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web"
    script_path = web_root / "scripts" / "bundle-budget.mjs"

    assert script_path.exists(), f"missing {script_path}"

    web_package = json.loads((web_root / "package.json").read_text())
    assert web_package["scripts"]["bundle:check"] == "node ./scripts/bundle-budget.mjs"

    script_text = script_path.read_text()
    budget = _script_budget(script_text)
    assert "export const defaultBudget" in script_text
    assert "dist/assets" in script_text
    assert "Missing web build assets" in script_text
    assert "pnpm --filter @focus-agent/web-app build" in script_text
    assert "--print-budget" in script_text
    assert budget["maxCssBytes"] >= budget["maxCssAssetBytes"] > 0
    assert budget["maxJsBytes"] >= budget["maxJsAssetBytes"] > 0


def test_react_web_app_scaffold_exists_and_uses_workspace_sdk():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web"

    required = [
        root / "package.json",
        root / "pnpm-workspace.yaml",
        root / "pnpm-lock.yaml",
        web_root / "package.json",
        web_root / "tsconfig.json",
        web_root / "vite.config.ts",
        web_root / "index.html",
        web_root / "src" / "main.tsx",
        web_root / "src" / "app" / "router.tsx",
        web_root / "src" / "app" / "providers" / "app-providers.tsx",
        web_root / "src" / "shared" / "sdk" / "focus-agent-provider.tsx",
        web_root / "src" / "shared" / "styles" / "app.css",
    ]

    for path in required:
        assert path.exists(), f"missing {path}"

    root_package = (root / "package.json").read_text()
    assert "web:check" in root_package
    assert "web:build" in root_package

    workspace = (root / "pnpm-workspace.yaml").read_text()
    assert "apps/*" in workspace
    assert "frontend-sdk" in workspace

    web_package = (web_root / "package.json").read_text()
    assert '"@focus-agent/web-app"' in web_package
    assert '"@focus-agent/web-sdk": "workspace:*"' in web_package
    assert '"@tanstack/react-query"' in web_package
    assert '"@tanstack/react-router"' in web_package
    assert '"react"' in web_package

    router_text = (web_root / "src" / "app" / "router.tsx").read_text()
    assert "ThreadPage" in router_text
    assert "AgentRoleConsolePage" in router_text
    assert 'path: "/agent/roles"' in router_text
    assert 'path: "/agent/governance"' in router_text
    assert 'path: "/auth"' in router_text
    assert 'path: "/auth/login"' in router_text
    assert 'path: "/auth/register"' in router_text
    assert 'path: "/admin/users/$userId"' in router_text
    assert "LoginPage" in router_text
    assert 'to: "/auth/login"' in router_text
    assert "AuthGate" in router_text
    assert "AppShell" in router_text
    assert "basepath: appEnv.routerBasePath" in router_text

    vite_text = (web_root / "vite.config.ts").read_text()
    assert 'process.env.VITE_FOCUS_AGENT_APP_BASE || "/app/"' in vite_text
    assert "base: appBase" in vite_text
    assert 'process.env.API_PORT || "8000"' in vite_text
    assert '"/v1": apiTarget' in vite_text
    assert '"/v2": apiTarget' in vite_text

    index_html_text = (web_root / "index.html").read_text()
    assert 'rel="icon"' in index_html_text
    assert 'new URLSearchParams(window.location.search).get("lang")' in index_html_text
    assert '["en", "zh"].includes(queryLanguage)' in index_html_text

    provider_text = (web_root / "src" / "shared" / "sdk" / "focus-agent-provider.tsx").read_text()
    assert "createDemoToken" in provider_text
    assert "getPrincipal" in provider_text
    assert "FocusAgentRequestError" in provider_text
    assert "clearStoredTokenAndReset" in provider_text
    assert "authHint" in provider_text
    assert "error.status === 401" in provider_text
    assert "authenticateWithToken" in provider_text
    assert "Demo token bootstrap is disabled" in provider_text
    assert "window.localStorage.removeItem" in provider_text

    merge_review_text = _join_text(
        web_root / "src" / "features" / "merge-review" / "merge-review-card.tsx",
        web_root / "src" / "features" / "merge-review" / "merge-review-sections.tsx",
        web_root / "src" / "features" / "merge-review" / "merge-review-utils.ts",
    )
    assert "useEffect" in merge_review_text
    assert "proposalSignature" in merge_review_text
    assert 'summary: proposal?.summary ?? ""' in merge_review_text
    assert "const recommendedMode = proposal?.recommended_import_mode;" in merge_review_text
    assert 'recommendedMode !== "none"' in merge_review_text
    assert ': "summary_only";' in merge_review_text

    conversation_toolbar_text = (
        web_root / "src" / "features" / "conversations" / "conversation-toolbar.tsx"
    ).read_text()
    assert 'to: "/c/$conversationId/t/$threadId"' in conversation_toolbar_text
    assert "threadId: rootThreadId" in conversation_toolbar_text

    app_shell_text = _shell_text(web_root)
    assert 'type ShellMode = "admin" | "agent-workbench" | "chat"' in app_shell_text
    assert "function isAgentWorkbenchPath" in app_shell_text
    assert "function resolveShellMode" in app_shell_text
    assert "function SidebarToggleIcon" in app_shell_text
    assert 'new URLSearchParams(window.location.search).get("lang")' in app_shell_text
    assert 'const MOBILE_SHELL_QUERY = "(max-width: 900px)"' in app_shell_text
    assert "globalThis.window?.matchMedia(MOBILE_SHELL_QUERY).matches" in app_shell_text
    assert 'setSidebarCollapsed(isMobileShellViewport() || stored === "1")' in app_shell_text
    assert 'state.location.pathname.includes("/agent-team")' not in app_shell_text
    assert 'state.location.pathname.includes("/admin/")' not in app_shell_text
    assert 'urlLanguage === "en" || urlLanguage === "zh"' in app_shell_text
    assert "window.localStorage.getItem(LANGUAGE_KEY)" in app_shell_text
    assert 'className="fa-sidebar-global-nav"' in app_shell_text
    assert 'className="fa-sidebar-dock"' in app_shell_text
    assert 'className="fa-sidebar-account"' in app_shell_text
    assert 'className="fa-sidebar-account-avatar"' in app_shell_text
    assert "已登录" not in app_shell_text
    assert "lastChatTarget" in app_shell_text
    assert "lastAgentTeamTarget" in app_shell_text
    assert "lastAdminTarget" not in app_shell_text
    assert "rootThreadSearch" in app_shell_text
    assert 'pathname === "/observability/overview"' in app_shell_text
    assert 'pathname === "/observability/trajectory"' in app_shell_text
    assert 'pathname === "/agent/governance"' in app_shell_text
    assert 'pathname === "/agent/roles"' in app_shell_text
    assert "isDiagnosticsRoute" not in app_shell_text
    assert "const chatNavLabel" in app_shell_text
    assert "const productivityNavLabel" in app_shell_text
    assert "const agentTeamNavLabel" in app_shell_text
    assert "const adminNavLabel" in app_shell_text
    assert "const sidebarToggleLabel" in app_shell_text
    assert "const currentAccountLabel" in app_shell_text
    assert "const currentAccountTooltip" in app_shell_text
    assert "aria-label={currentAccountTooltip}" in app_shell_text
    assert "tooltipProps(currentAccountTooltip)" in app_shell_text
    assert "aria-label={chatNavLabel}" in app_shell_text
    assert "aria-label={productivityNavLabel}" in app_shell_text
    assert "aria-label={adminNavLabel}" in app_shell_text
    assert "chatNavTarget ? (" in app_shell_text
    assert "tooltipProps(adminNavLabel)" in app_shell_text
    assert "tooltipProps(productivityNavLabel)" in app_shell_text
    assert 'to="/productivity/tasks"' in app_shell_text
    assert "agentTeamRootThreadId" in app_shell_text
    assert "is-${shellMode}-shell" in app_shell_text
    assert "fa-workspace-sidebar-toggle" in app_shell_text
    assert '"fa-workspace-sidebar"' in app_shell_text
    assert "isChatShell ? (" in app_shell_text
    assert 'to="/agent-team"' in app_shell_text
    assert 'to="/observability/overview"' in app_shell_text
    assert 'to="/agent/governance"' in app_shell_text
    assert 'to="/admin/config"' in app_shell_text
    assert 'to="/admin/users"' in app_shell_text
    assert 'to="/admin/audit-events"' in app_shell_text
    global_navigation_text = (
        web_root / "src" / "app" / "shell" / "app-shell-global-navigation.tsx"
    ).read_text()
    assert "{isAdmin ? (" not in global_navigation_text
    assert "AdminAccessGate" not in global_navigation_text
    assert 'const agentTeamNavLabel = isChineseUi ? "团队" : "Team";' in global_navigation_text
    assert "appEnv.features.agentTeam ? (" in global_navigation_text
    assert "aria-label={agentTeamNavLabel}" in global_navigation_text
    assert "tooltipProps(agentTeamNavLabel)" in global_navigation_text
    assert "AgentTeamIcon" in global_navigation_text
    assert 'to="/agent-team"' in global_navigation_text
    sidebar_copy_text = (
        web_root / "src" / "app" / "shell" / "app-shell-sidebar-brand.tsx"
    ).read_text()
    assert "fa-sidebar-global-nav" not in sidebar_copy_text
    chat_header_actions_text = (
        web_root / "src" / "app" / "shell" / "app-shell-chat-header.tsx"
    ).read_text()
    assert 'to="/agent-team"' not in chat_header_actions_text
    assert 'to="/admin/users"' not in chat_header_actions_text
    assert "SessionExitIcon" not in chat_header_actions_text

    styles_text = _web_styles(web_root)
    assert ".fa-auth-bootstrap-card" in styles_text
    assert ".fa-auth-bootstrap-input" in styles_text
    assert ".fa-auth-hub" in styles_text
    assert ".fa-sidebar-global-nav" in styles_text
    assert "container-name: fa-sidebar;" in styles_text
    assert "@container fa-sidebar (max-width: 420px)" in styles_text
    assert "flex-wrap: nowrap;" in styles_text
    assert "grid-template-columns: auto minmax(0, 1fr);" in styles_text
    assert "font-size: 0.64rem;" in styles_text
    assert ".fa-sidebar-dock .fa-sidebar-nav-link span:last-child" in styles_text
    assert ".fa-sidebar-dock .fa-sidebar-account-avatar" in styles_text
    assert ".fa-sidebar-dock .fa-sidebar-account-copy em" in styles_text
    assert ".fa-sidebar-dock .fa-sidebar-account-copy strong" in styles_text
    assert "justify-content: flex-end;" in styles_text
    assert ".fa-workspace-sidebar-toggle" in styles_text
    assert ".fa-app-shell.is-sidebar-collapsed.is-agent-workbench-shell" in styles_text
    assert ".fa-app-shell:not(.is-sidebar-collapsed)::before" in styles_text
    assert ".fa-sidebar-panel.is-global-shell" in styles_text
    assert ".fa-workspace-sidebar-toggle span" in styles_text
    assert ".fa-workspace-sidebar-item" in styles_text
    assert ".fa-chat-main-body.is-agent-workbench-route > .fa-observability-layout" in styles_text
    assert ".fa-sidebar-dock" in styles_text
    assert ".fa-sidebar-account" in styles_text
    assert ".fa-sidebar-account-avatar" in styles_text
    assert ".fa-workspace-sidebar" in styles_text
    assert ".fa-chat-panel.is-workspace-shell" in styles_text
    assert ".fa-agent-team-workspace-shell" in styles_text
    assert ".fa-admin-page-bar" in styles_text

    agent_team_text = (
        web_root / "src" / "features" / "agent-team" / "agent-team-workbench.tsx"
    ).read_text()
    assert "fa-agent-team-workspace-shell" in agent_team_text
    assert "fa-agent-team-stage" in agent_team_text
    assert "AgentTeamCockpit" in agent_team_text
    assert "AgentTeamRouteTabs" not in agent_team_text

    admin_chrome_text = (web_root / "src" / "pages" / "admin" / "admin-page-chrome.tsx").read_text()
    admin_heading_text = admin_chrome_text.split("export function AdminPageHeading", maxsplit=1)[
        1
    ].split(
        "export function AdminErrorMessage",
        maxsplit=1,
    )[0]
    assert "SessionExitIcon" not in admin_chrome_text
    assert "logout" not in admin_heading_text
    assert "退出登录" not in admin_heading_text
    assert "fa-admin-page-bar" in admin_heading_text
    assert "系统管理 / 治理" in admin_heading_text

    agent_console_text = _join_text(
        web_root / "src" / "pages" / "agents" / "agent-role-console-page.tsx",
        web_root / "src" / "pages" / "agents" / "agent-role-console-hooks.ts",
        web_root / "src" / "pages" / "agents" / "agent-role-console-policy-panels.tsx",
        web_root / "src" / "pages" / "agents" / "agent-role-console-preview-panels.tsx",
        web_root / "src" / "pages" / "agents" / "agent-role-console-trajectory-panels.tsx",
        web_root / "src" / "pages" / "agents" / "agent-role-console-view-model.ts",
    )
    assert "Delegation Runs" in agent_console_text
    assert 'to="/observability/overview"' not in agent_console_text
    assert 'to="/agent/governance"' not in agent_console_text
    assert "Model Router" in agent_console_text
    assert "Self Repair" in agent_console_text
    assert "Review Queue" in agent_console_text
    assert "Context Engineering v2" in agent_console_text
    assert "Task Ledger" in agent_console_text
    assert "Delegated Artifacts" in agent_console_text
    assert "Critic Gate" in agent_console_text
    assert "listAgentDelegationRuns" in agent_console_text
    assert "previewAgentContext" in agent_console_text
    assert "listAgentContextArtifacts" in agent_console_text
    assert "planAgentTaskLedger" in agent_console_text
    assert "listAgentArtifacts" in agent_console_text

    query_keys_text = (web_root / "src" / "shared" / "query" / "query-keys.ts").read_text()
    assert "agentContextPolicy" in query_keys_text
    assert "agentContextArtifacts" in query_keys_text
    assert "agentTaskLedgerPolicy" in query_keys_text
    assert "agentCriticVerdicts" in query_keys_text

    stream_hook_text = (
        web_root / "src" / "features" / "thread-stream" / "use-thread-stream.ts"
    ).read_text()
    assert "let sendSucceeded = false;" in stream_hook_text
    assert "nextState.isClosed && !nextState.failed && !controller.signal.aborted" in _compact(
        stream_hook_text
    )
    stream_errors_text = (
        web_root / "src" / "features" / "thread-stream" / "use-thread-stream-errors.ts"
    ).read_text()
    stream_cache_text = (
        web_root / "src" / "features" / "thread-stream" / "use-thread-stream-cache.ts"
    ).read_text()
    stream_registry_text = (
        web_root / "src" / "features" / "thread-stream" / "use-stream-request-registry.ts"
    ).read_text()
    assert "failed: {" in stream_errors_text
    assert "resolveStreamRequestCleanup( sendSucceeded, controller.signal.aborted, )" in _compact(
        stream_hook_text
    )
    assert "pendingUserMessage: cleanup.clearPendingUserMessage" in stream_hook_text
    assert 'event.event === "run.completed"' in stream_hook_text
    assert "queryClient.setQueryData(" in stream_cache_text
    assert "queryKeys.thread(threadId)" in stream_cache_text
    assert "Promise.allSettled([" in stream_cache_text
    assert 'error.name === "AbortError"' in stream_errors_text
    assert "sendSucceeded = false;" in stream_hook_text
    assert "client.sendTurn(" not in stream_hook_text
    assert "isCurrentStreamRequest" in stream_registry_text

    sdk_root = root / "frontend-sdk" / "src"
    sdk_index_text = (sdk_root / "index.ts").read_text()
    sdk_reducer_text = (sdk_root / "reducers.ts").read_text()
    sdk_tool_protocol_text = (sdk_root / "toolProtocol.ts").read_text()
    assert 'export * from "./toolProtocol.js";' in sdk_index_text
    assert "safeVisibleTextTransition(" in sdk_reducer_text
    assert "safeVisibleText(value)" in sdk_reducer_text
    assert "looksLikeTextualToolCallArtifact" in sdk_tool_protocol_text
    assert "web_fetch" in sdk_tool_protocol_text


def test_react_web_app_restores_merged_branch_read_only_mode():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web" / "src"

    thread_page_text = _join_text(
        web_root / "pages" / "thread" / "thread-page.tsx",
        web_root / "pages" / "thread" / "thread-page-content.tsx",
        web_root / "pages" / "thread" / "use-thread-branch-actions.ts",
    )
    composer_text = _join_text(
        web_root / "features" / "thread-stream" / "message-composer.tsx",
        web_root / "features" / "thread-stream" / "message-composer-helpers.ts",
        web_root / "features" / "thread-stream" / "message-composer-submit.ts",
        web_root / "entities" / "messages" / "message-list-helpers.ts",
    )
    message_list_text = _join_text(
        web_root / "entities" / "messages" / "message-list.tsx",
        web_root / "entities" / "messages" / "message-list-actions.tsx",
        web_root / "entities" / "messages" / "message-list-branch-action-card.tsx",
        web_root / "entities" / "messages" / "message-list-tool-activity-card.tsx",
    )
    header_actions_text = _join_text(
        web_root / "features" / "thread" / "thread-header-actions.tsx",
        web_root / "features" / "thread" / "thread-header-action-buttons.tsx",
        web_root / "features" / "thread" / "thread-header-action-labels.ts",
    )
    branch_tree_text = _join_text(
        web_root / "features" / "branch-tree" / "branch-tree-panel.tsx",
        web_root / "features" / "branch-tree" / "branch-tree-graph-toolbar.tsx",
        web_root / "features" / "branch-tree" / "branch-tree-helpers.ts",
    )
    app_shell_text = _shell_text(root / "apps" / "web")
    merge_review_text = _join_text(
        web_root / "features" / "merge-review" / "merge-review-card.tsx",
        web_root / "features" / "merge-review" / "merge-review-sections.tsx",
        web_root / "features" / "merge-review" / "merge-review-utils.ts",
    )
    thread_retry_text = _join_text(
        web_root / "shared" / "thread" / "retry-thread-busy-conflict.ts",
        web_root / "features" / "branch-tree" / "use-branch-actions.ts",
        web_root / "pages" / "thread" / "use-thread-branch-actions.ts",
    )

    assert 'branch_meta?.branch_status === "merged"' in thread_page_text
    assert "isReadOnly={isMergedReadOnlyThread}" in thread_page_text
    assert "if (!trimmed || isStreaming || isReadOnly) return;" in composer_text
    assert "const wasEditing = Boolean(editDraft);" in composer_text
    assert "if (wasEditing) {" in composer_text
    assert "result = await onSendMessage(" in composer_text
    assert "trimmed," in composer_text
    assert "if (!result.ok && !result.aborted) {" in composer_text
    assert "restoreSubmittedDraft();" in composer_text
    assert "onClearEditDraft?.();" in composer_text
    assert "readOnly={isReadOnly}" in composer_text
    assert "disabled={isStreaming || isReadOnly || !message.trim()}" in composer_text
    assert "disabled={isReadOnly}" in message_list_text
    assert "isReadOnly={isReadOnly || isStreaming}" in message_list_text
    assert "retryThreadBusyConflict" in thread_retry_text
    assert "THREAD_BUSY_RETRY_ATTEMPTS" in thread_retry_text
    assert "ThreadBranchActionRetryCancelled" in thread_retry_text
    assert "client.prepareMergeProposal(threadId)" in thread_retry_text
    assert "branchActionRequestEpochRef" in thread_page_text
    assert "isCurrentBranchActionRequest" in thread_page_text
    assert "}, [threadId]);" in thread_page_text
    assert "Merged branches are read-only" in composer_text
    assert 'const isMergedBranch = branchMeta?.branch_status === "merged";' in header_actions_text
    assert "disabled={!threadId || isMergedBranch || isCreatingBranch}" in header_actions_text
    assert "Merged branches cannot create new branches" in header_actions_text
    assert "Merged branches cannot generate or merge conclusions" in header_actions_text
    assert "if (!isReviewRoute && isMergedBranch) return;" in header_actions_text
    assert "isWorking ||" in header_actions_text
    assert "(!isReviewRoute && (isGeneratingConclusion || isMergedBranch))" in header_actions_text
    assert (
        'const isMergedCreateTarget = createBranchTargetNode?.branch_status === "merged";'
        in _compact(branch_tree_text)
    )
    assert "createBranchDisabled={isMergedCreateTarget || isCreatingBranch}" in branch_tree_text
    assert "disabled={!canCreateBranch || createBranchDisabled}" in branch_tree_text
    assert "Create a branch from the selected node" in branch_tree_text
    assert "Merged branches cannot create new branches" in branch_tree_text
    assert 'activeThreadState?.branch_meta?.branch_status === "merged"' in app_shell_text
    assert "Merged branches cannot generate or merge conclusions." in app_shell_text
    assert 'const isMergedBranch = pendingStatus === "merged";' in merge_review_text
    assert "disabled={isSubmitting || isMergedBranch}" in merge_review_text


def test_react_primitives_keep_modal_and_drawer_backdrops_out_of_tab_order():
    root = Path(__file__).resolve().parents[1]
    primitives_text = (
        root / "apps" / "web" / "src" / "shared" / "ui" / "primitives" / "index.tsx"
    ).read_text()

    assert 'aria-label="Close modal"' in primitives_text
    assert 'aria-label="Close drawer"' in primitives_text
    assert primitives_text.count("tabIndex={-1}") >= 2


def test_react_web_app_hides_raw_tool_messages_behind_compact_activity_cards():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web" / "src"

    thread_page_text = (web_root / "pages" / "thread" / "thread-page.tsx").read_text()
    message_list_text = _join_text(
        web_root / "entities" / "messages" / "message-list.tsx",
        web_root / "entities" / "messages" / "message-list-tool-activity-card.tsx",
    )
    message_transcript_text = _join_text(
        web_root / "entities" / "messages" / "message-transcript.ts",
        web_root / "entities" / "messages" / "message-transcript-builder.ts",
        web_root / "entities" / "messages" / "message-transcript-visibility.ts",
    )
    styles_text = _web_styles(root / "apps" / "web")

    assert "assistantMessage={data?.assistant_message}" in thread_page_text
    assert "buildTranscriptItems(messages, assistantMessage)" in message_list_text
    assert "looksLikeInternalToolMarkup" in message_transcript_text
    assert "looksLikeTextualToolCallArtifact" in message_transcript_text
    assert 'kind: "tool-activity"' in message_transcript_text
    assert 'className="fa-tool-activity-card"' in message_list_text
    assert "id: `${lastItem.id}-summary`" not in message_transcript_text
    assert ".fa-tool-activity-card" in styles_text
    assert ".fa-tool-activity-summary" in styles_text


def test_react_web_app_marks_merged_branch_status_in_danger_tone():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web" / "src"

    branch_tree_text = _join_text(
        web_root / "features" / "branch-tree" / "branch-tree-panel.tsx",
        web_root / "features" / "branch-tree" / "branch-tree-helpers.ts",
    )
    styles_text = _web_styles(root / "apps" / "web")

    assert 'case "awaiting_merge_review": return "is-ready";' in _compact(branch_tree_text)
    assert 'case "merged": return "is-merged";' in _compact(branch_tree_text)
    assert ".fa-branch-node-badge.is-danger" in styles_text
    assert ".fa-archived-item-status.is-danger" in styles_text


def test_conversation_rename_uses_inline_form_not_browser_prompt():
    root = Path(__file__).resolve().parents[1]
    conversation_toolbar_text = _join_text(
        root / "apps" / "web" / "src" / "features" / "conversations" / "conversation-toolbar.tsx",
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "conversations"
        / "conversation-toolbar-view.tsx",
    )
    branch_tree_text = _join_text(
        root / "apps" / "web" / "src" / "features" / "branch-tree" / "branch-tree-panel.tsx",
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "branch-tree"
        / "branch-tree-detail-overlay.tsx",
    )
    styles_text = _web_styles(root / "apps" / "web")

    assert "const conversation = await createConversation();" in conversation_toolbar_text
    assert "window.prompt" not in conversation_toolbar_text
    assert "window.prompt" not in branch_tree_text
    assert "fa-conversation-rename-button" in conversation_toolbar_text
    assert "RenameConversationIcon" in conversation_toolbar_text
    assert "onClick={onRenameActiveConversation}" in conversation_toolbar_text
    assert 'className="fa-inline-rename-form is-conversation"' in conversation_toolbar_text
    assert 'className="fa-inline-rename-form is-branch-title"' in branch_tree_text
    assert "onDoubleClick={() => onStartRename(detailNode)}" in branch_tree_text
    assert ".fa-inline-rename-input" in styles_text


def test_thread_header_allows_double_click_current_branch_rename():
    root = Path(__file__).resolve().parents[1]
    thread_header_text = _join_text(
        root / "apps" / "web" / "src" / "features" / "thread" / "thread-header-actions.tsx",
        root / "apps" / "web" / "src" / "features" / "thread" / "thread-header-action-buttons.tsx",
    )

    assert "onDoubleClick={handleRenameBranchDoubleClick}" in thread_header_text
    assert "onRenameCurrentBranch();" in thread_header_text
    assert 'className="fa-inline-rename-form is-header-branch is-inline"' in thread_header_text
    assert "await renameBranch(threadId, nextName);" in thread_header_text


def test_chat_header_rename_modes_are_mutually_exclusive():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web"
    app_shell_text = (web_root / "src" / "app" / "shell" / "app-shell-chat-header.tsx").read_text()
    conversation_toolbar_text = (
        web_root / "src" / "features" / "conversations" / "conversation-toolbar.tsx"
    ).read_text()
    thread_header_actions_text = (
        web_root / "src" / "features" / "thread" / "thread-header-actions.tsx"
    ).read_text()
    thread_header_buttons_text = (
        web_root / "src" / "features" / "thread" / "thread-header-action-buttons.tsx"
    ).read_text()
    styles_text = _web_styles(web_root)
    responsive_styles_text = (
        web_root / "src" / "shared" / "styles" / "overrides-responsive.css"
    ).read_text()
    compact_shell_text = _compact(app_shell_text)
    compact_conversation_text = _compact(conversation_toolbar_text)
    compact_thread_text = _compact(thread_header_actions_text)

    assert 'export type HeaderRenameScope = "conversation" | "branch" | null;' in app_shell_text
    assert "export type HeaderRenameScopeSetter = Dispatch<" in app_shell_text
    assert "useState<HeaderRenameScope>(null)" in app_shell_text
    assert (
        "<ConversationToolbar activeRenameScope={activeRenameScope} "
        "onRenameScopeChange={setActiveRenameScope} />" in compact_shell_text
    )
    assert (
        "<ThreadHeaderActions activeRenameScope={activeRenameScope} "
        "onRenameScopeChange={setActiveRenameScope} "
        "onRequestOpenSidebar={onOpenSidebar} />" in compact_shell_text
    )
    assert 'onRenameScopeChange?.("conversation");' in conversation_toolbar_text
    assert (
        "const visibleRenameTarget = canShowConversationRename ? renameTarget : null;"
        in conversation_toolbar_text
    )
    assert "renameTarget={visibleRenameTarget}" in conversation_toolbar_text
    assert 'currentScope === "conversation" ? null : currentScope' in conversation_toolbar_text
    assert (
        'activeRenameScope !== undefined && activeRenameScope !== "conversation"'
        in compact_conversation_text
    )
    assert "setRenameTarget(null);" in conversation_toolbar_text
    assert 'setRenameDraft("");' in conversation_toolbar_text
    assert 'onRenameScopeChange?.("branch");' in thread_header_actions_text
    assert "const isBranchRenameVisible =" in thread_header_actions_text
    assert "isRenamingCurrentBranch={isBranchRenameVisible}" in thread_header_actions_text
    assert 'currentScope === "branch" ? null : currentScope' in thread_header_actions_text
    assert (
        'activeRenameScope !== undefined && activeRenameScope !== "branch"' in compact_thread_text
    )
    assert "setIsRenamingCurrentBranch(false);" in thread_header_actions_text
    assert 'setRenameBranchDraft("");' in thread_header_actions_text
    assert "onCancelRenameCurrentBranch={cancelRenameCurrentBranch}" in thread_header_actions_text
    assert (
        'className="fa-chat-toolbar-pill fa-focus-branches-button is-renaming"'
        in thread_header_buttons_text
    )
    assert (
        'className="fa-chat-toolbar-pill fa-focus-branches-button is-renaming" '
        'data-compact-button="true"' not in _compact(thread_header_buttons_text)
    )
    assert ".fa-focus-branches-button:not(.is-renaming)" in styles_text
    assert (
        ".fa-chat-header-actions.is-compact .fa-focus-branches-button:not(.is-renaming)"
        in styles_text
    )
    assert "max-width: min(360px, max(220px, 38vw));" in styles_text
    assert ".fa-chat-header-right-actions:has(.fa-focus-branches-button.is-renaming)" in styles_text
    assert ".fa-chat-header-actions:has(.fa-focus-branches-button.is-renaming)" in styles_text
    assert (
        ".fa-chat-header-actions:has(.fa-focus-branches-button.is-renaming) .fa-new-branch-button"
        in _compact(styles_text)
    )
    assert (
        ".fa-chat-header-actions:has(.fa-focus-branches-button.is-renaming) .fa-review-button"
        in _compact(styles_text)
    )
    assert (
        ".fa-chat-header-actions:has(.fa-focus-branches-button.is-renaming) .fa-chat-header-nav"
        in _compact(styles_text)
    )
    assert (
        ".fa-chat-header-top:has(.fa-focus-branches-button.is-renaming) .fa-conversation-switcher"
        in _compact(styles_text)
    )
    assert (
        ".fa-chat-header-top:has(.fa-focus-branches-button.is-renaming) .fa-conversation-jump"
        in _compact(styles_text)
    )
    assert "calc(100vw - 48px)" in responsive_styles_text


def test_thread_header_new_branch_stays_enabled_during_conclusion_generation():
    root = Path(__file__).resolve().parents[1]
    thread_header_text = (
        root / "apps" / "web" / "src" / "features" / "thread" / "thread-header-action-buttons.tsx"
    ).read_text()

    assert (
        'className="fa-chat-toolbar-button is-primary fa-new-branch-button"' in thread_header_text
    )
    assert "disabled={!threadId || isMergedBranch || isCreatingBranch}" in thread_header_text
    assert "!threadId || isWorking || isMergedBranch || isCreatingBranch" not in thread_header_text


def test_conversation_switcher_only_lists_active_conversations():
    root = Path(__file__).resolve().parents[1]
    conversation_toolbar_text = _join_text(
        root / "apps" / "web" / "src" / "features" / "conversations" / "conversation-toolbar.tsx",
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "conversations"
        / "conversation-toolbar-view.tsx",
    )

    assert "const archivedConversations" not in conversation_toolbar_text
    assert "<optgroup" not in conversation_toolbar_text
    assert "disabled={ isLoading || isWorking || activeConversations.length === 0 }" in _compact(
        conversation_toolbar_text
    )
    assert "activeConversations.find(" in conversation_toolbar_text
    assert "conversation.root_thread_id === conversationId" in conversation_toolbar_text
    assert "?? activeConversations[0]" in conversation_toolbar_text


def test_archived_sidebar_sections_are_collapsible_and_compact():
    root = Path(__file__).resolve().parents[1]
    branch_tree_text = _join_text(
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "branch-tree"
        / "branch-tree-archived-sections.tsx",
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "branch-tree"
        / "branch-tree-archived-state.ts",
    )
    styles_text = _web_styles(root / "apps" / "web")

    assert branch_tree_text.index('已归档会话" : "Archived conversations') < branch_tree_text.index(
        '已归档分支" : "Archived branches'
    )
    assert "archivedConversationsExpanded," in branch_tree_text
    assert "setArchivedConversationsExpanded," in branch_tree_text
    assert "useState(archivedConversationsCount > 0)" in branch_tree_text
    assert "archivedBranchesExpanded," in branch_tree_text
    assert "setArchivedBranchesExpanded," in branch_tree_text
    assert "useState(" in branch_tree_text
    assert "archivedBranchesCount > 0" in branch_tree_text
    assert "展开或收起已归档会话" in branch_tree_text
    assert "Toggle archived conversations" in branch_tree_text
    assert "展开或收起已归档分支" in branch_tree_text
    assert "Toggle archived branches" in branch_tree_text
    assert "shouldShowArchivedSecondaryLine(" in branch_tree_text
    assert "conversation.title" in branch_tree_text
    assert "conversation.root_thread_id" in branch_tree_text
    assert "node.branch_name" in branch_tree_text
    assert "node.thread_id" in branch_tree_text

    archived_conversation_section = branch_tree_text.split(
        '{isChineseUi ? "已归档会话" : "Archived conversations"}',
        1,
    )[1].split('{isChineseUi ? "已归档分支" : "Archived branches"}', 1)[0]
    assert "fa-archived-item-status" not in archived_conversation_section
    assert '{isChineseUi ? "打开" : "Open"}' in archived_conversation_section
    assert '{isChineseUi ? "恢复" : "Restore"}' in archived_conversation_section

    assert ".fa-tree-section-header" in styles_text
    assert ".fa-tree-section-toggle" in styles_text
    assert ".fa-tree-section-toggle.is-collapsed svg" in styles_text
    assert ".fa-archived-item-head" in styles_text
    assert ".fa-archived-item-toolbar" in styles_text
