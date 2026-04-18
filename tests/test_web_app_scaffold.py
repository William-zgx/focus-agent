from pathlib import Path


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
    assert 'apps/*' in workspace
    assert 'frontend-sdk' in workspace

    web_package = (web_root / "package.json").read_text()
    assert '"@focus-agent/web-app"' in web_package
    assert '"@focus-agent/web-sdk": "workspace:*"' in web_package
    assert '"@tanstack/react-query"' in web_package
    assert '"@tanstack/react-router"' in web_package
    assert '"react"' in web_package

    router_text = (web_root / "src" / "app" / "router.tsx").read_text()
    assert "ThreadPage" in router_text
    assert "AppShell" in router_text
    assert 'basepath: "/app"' in router_text

    vite_text = (web_root / "vite.config.ts").read_text()
    assert 'base: "/app/"' in vite_text

    index_html_text = (web_root / "index.html").read_text()
    assert 'rel="icon"' in index_html_text
    assert 'new URLSearchParams(window.location.search).get("lang")' in index_html_text
    assert '["en", "zh"].includes(queryLanguage)' in index_html_text

    provider_text = (web_root / "src" / "shared" / "sdk" / "focus-agent-provider.tsx").read_text()
    assert "createDemoToken" in provider_text
    assert "getPrincipal" in provider_text
    assert "FocusAgentRequestError" in provider_text
    assert "clearStoredToken()" in provider_text
    assert "error.status === 401" in provider_text
    assert "window.localStorage.removeItem" in provider_text

    merge_review_text = (web_root / "src" / "features" / "merge-review" / "merge-review-card.tsx").read_text()
    assert "useEffect" in merge_review_text
    assert "proposalSignature" in merge_review_text
    assert "setSummary(proposal?.summary ?? \"\")" in merge_review_text
    assert "setMode(proposal?.recommended_import_mode ?? \"summary_only\")" in merge_review_text

    conversation_toolbar_text = (
        web_root / "src" / "features" / "conversations" / "conversation-toolbar.tsx"
    ).read_text()
    assert 'to: "/c/$conversationId/t/$threadId"' in conversation_toolbar_text
    assert "threadId: rootThreadId" in conversation_toolbar_text

    app_shell_text = (web_root / "src" / "app" / "shell" / "app-shell.tsx").read_text()
    assert 'new URLSearchParams(window.location.search).get("lang")' in app_shell_text
    assert 'urlLanguage === "en" || urlLanguage === "zh"' in app_shell_text
    assert 'window.localStorage.getItem(LANGUAGE_KEY)' in app_shell_text

    stream_hook_text = (
        web_root / "src" / "features" / "thread-stream" / "use-thread-stream.ts"
    ).read_text()
    assert "setStreamState(null)" in stream_hook_text


def test_react_web_app_restores_merged_branch_read_only_mode():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web" / "src"

    thread_page_text = (web_root / "pages" / "thread" / "thread-page.tsx").read_text()
    composer_text = (web_root / "features" / "thread-stream" / "message-composer.tsx").read_text()
    message_list_text = (web_root / "entities" / "messages" / "message-list.tsx").read_text()
    header_actions_text = (web_root / "features" / "thread" / "thread-header-actions.tsx").read_text()
    branch_tree_text = (web_root / "features" / "branch-tree" / "branch-tree-panel.tsx").read_text()

    assert 'branch_meta?.branch_status === "merged"' in thread_page_text
    assert "isReadOnly={isMergedReadOnlyThread}" in thread_page_text
    assert "if (!trimmed || isStreaming || isReadOnly) return;" in composer_text
    assert "readOnly={isReadOnly}" in composer_text
    assert "disabled={isStreaming || isReadOnly || !message.trim()}" in composer_text
    assert "disabled={isReadOnly}" in message_list_text
    assert "Merged branches are read-only" in composer_text
    assert 'const isMergedBranch = branchMeta?.branch_status === "merged";' in header_actions_text
    assert 'disabled={!threadId || isWorking || isMergedBranch || isCreatingBranch}' in header_actions_text
    assert "Merged branches cannot create new branches" in header_actions_text
    assert 'const isMergedCreateTarget = createBranchTargetNode?.branch_status === "merged";' in branch_tree_text
    assert 'disabled={!createBranchTargetThreadId || isMergedCreateTarget || isCreatingBranch}' in branch_tree_text
    assert "Create a branch from the selected node" in branch_tree_text
    assert "Merged branches cannot create new branches" in branch_tree_text


def test_react_web_app_hides_raw_tool_messages_behind_compact_activity_cards():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web" / "src"

    thread_page_text = (web_root / "pages" / "thread" / "thread-page.tsx").read_text()
    message_list_text = (web_root / "entities" / "messages" / "message-list.tsx").read_text()
    styles_text = (web_root / "shared" / "styles" / "app.css").read_text()

    assert "assistantMessage={data?.assistant_message}" in thread_page_text
    assert "buildTranscriptItems(messages, assistantMessage)" in message_list_text
    assert 'kind: "tool-activity"' in message_list_text
    assert 'className="fa-tool-activity-card"' in message_list_text
    assert 'id: `${lastItem.id}-summary`' in message_list_text
    assert ".fa-tool-activity-card" in styles_text
    assert ".fa-tool-activity-summary" in styles_text


def test_react_web_app_marks_merged_branch_status_in_danger_tone():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web" / "src"

    branch_tree_text = (web_root / "features" / "branch-tree" / "branch-tree-panel.tsx").read_text()
    styles_text = (web_root / "shared" / "styles" / "app.css").read_text()

    assert 'case "awaiting_merge_review":\n      return "is-ready";' in branch_tree_text
    assert 'case "merged":\n      return "is-merged";' in branch_tree_text
    assert ".fa-branch-node-badge.is-danger" in styles_text
    assert ".fa-archived-item-status.is-danger" in styles_text
