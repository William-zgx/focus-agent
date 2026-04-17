from focus_agent.web.app_shell import render_chat_app_html


def test_render_chat_app_html_defaults_to_english():
    html = render_chat_app_html()

    assert "Focus Agent" in html
    assert "Branch-aware research chat with a focused conversation view." not in html
    assert "New branch" in html
    assert "Refresh branches" in html
    assert "Archived branches" in html
    assert "No archived branches." in html
    assert "Archive" in html
    assert "Activate" in html
    assert "composer-create-branch" in html
    assert "composer-create-branch-label" in html
    assert "thread-nav" in html
    assert "focus-branch-tree" in html
    assert "prepare-merge" in html
    assert 'id="open-skills"' not in html
    assert 'id="skills-modal"' not in html
    assert "composer-input-shell" in html
    assert "composer-edit-banner" in html
    assert "composer-edit-cancel" in html
    assert "composer-footer-row" in html
    assert "composer-actions-row" in html
    assert "composer-model-row" in html
    assert html.index("composer-actions-row") < html.index("composer-model-row")
    assert 'id="composer-model-trigger"' in html
    assert 'id="composer-model-panel"' in html
    assert 'id="composer-model-list"' in html
    assert 'id="composer-model-trigger-logo"' in html
    assert 'id="stop-stream"' in html
    assert 'id="stop-stream-label"' in html
    assert "composer-model-thinking-toggle" in html
    assert 'id="composer-thinking-shell"' not in html
    assert "composer-model-logo-shell" in html
    assert "models.dev/logos/" in html
    assert "Loading models..." in html
    assert "Choose a model" in html
    assert "command palette" in html
    assert "Thinking mode" in html
    assert "Thinking unavailable" in html
    assert 'function pageDefaultThinkingModeForModel(model)' in html
    assert 'return normalizeThinkingMode(preferredMode) || pageDefaultThinkingModeForModel(model);' in html
    assert "composer-actions-note" in html
    assert "branch-tree-panel" in html
    assert 'id="conversation-select"' in html
    assert 'id="conversation-rename"' in html
    assert 'id="conversation-archive"' in html
    assert 'data-tooltip="Rename conversation"' in html
    assert 'data-tooltip="Archive conversation"' in html
    assert "Loading conversations..." in html
    assert "Switch or create a conversation" in html
    assert "Rename conversation" in html
    assert "Archive conversation" in html
    assert "Rename node" in html
    assert "Merged branches are read-only" in html
    assert "function mergedBranchReadOnlyLabel()" in html
    assert 'function isMergedReadOnlyThread(branchMeta = state.activeBranchMeta)' in html
    assert 'sidebarButton.disabled = isCreating || hitDepthLimit || isReadOnly;' in html
    assert 'toolbarButton.disabled = isCreating || hitDepthLimit || isReadOnly;' in html
    assert 'function syncComposerReadOnlyUi()' in html
    assert 'inputShell.classList.toggle("is-readonly", isReadOnly);' in html
    assert 'input.readOnly = isReadOnly;' in html
    assert 'sendButton.disabled = isReadOnly;' in html
    assert 'disabledLabel: isReadOnly ? mergedBranchReadOnlyLabel() : editMessageActionLabel(),' in html
    assert 'disabledLabel: isReadOnly ? mergedBranchReadOnlyLabel() : regenerateMessageActionLabel(),' in html
    assert "branch-graph" in html
    assert "tree-graph-legend" in html
    assert "branch-graph-root-label" in html
    assert "branch-graph-node-shell" in html
    assert "branch-node-detail" in html
    assert "renderGraphNode" in html
    assert "BRANCH_DETAIL_HIDE_DELAY_MS" in html
    assert "scheduleHideBranchDetail" in html
    assert 'branchDetailOverlay().addEventListener("focusout"' in html
    assert 'function tooltipTextForHost(host)' in html
    assert 'function tooltipAnchorForHost(host)' in html
    assert "mainTimelineLabel" in html
    assert "Hover or click any node to inspect its branch details" in html
    assert "brand-lockup" in html
    assert "chat-brand-lockup" in html
    assert "chat-logo-toggle" in html
    assert "brand-mark" in html
    assert "focus-agent-brand-accent" in html
    assert "focus-agent-chat-brand-accent" in html
    assert 'id="tree-branch-count-summary"' in html
    assert "In progress 0 · Archived 0" in html
    assert html.index("Refresh branches") < html.index("tree-branch-count-summary")
    assert 'id="sidebar-panel"' in html
    assert 'aria-controls="sidebar-panel"' in html
    assert "chat-header-primary-actions" in html
    assert "chat-header-nav" in html
    assert '<div class="chat-header-settings">' not in html
    assert "sidebar-settings" in html
    assert "chat-header-bottom" not in html
    assert "tree-title-row" in html
    assert ".tree-title-row h3" in html
    assert 'id="app-shell"' in html
    assert 'id="toggle-tree"' in html
    assert 'id="tree-panel-body"' in html
    assert "Collapse sidebar" in html
    assert "Show branches" in html
    assert "Traditional chatbot-style conversation with branch switching on the left." not in html
    assert 'id="stream-status"' not in html
    assert 'id="status-feed"' not in html
    assert "agent-status-panel" not in html
    assert "agent-run-bubble" in html
    assert "createAgentActivityBubble" in html
    assert "ensureAssistantBubble" in html
    assert "completedThreadStateById: {}" in html
    assert "treeLoadRequestId: 0" in html
    assert "threadLoadRequestId: 0" in html
    assert "conversationSelectionRequestId: 0" in html
    assert "streamingThreadId: null" in html
    assert "state.streamingThreadId === state.activeThreadId" in html
    assert 'id="language-select"' in html
    assert '<select id="language-select">' not in html
    assert "Language" in html
    assert "English" in html
    assert "中文" in html
    assert "panel-resizer" in html
    assert "info-trigger" in html
    assert "Back to main" in html
    assert "Back one level" in html
    assert "Generate conclusion" in html
    assert "Regenerate conclusion" in html
    assert "Merge target" in html
    assert "Open questions" in html
    assert 'id="merge-proposal-open-questions"' in html
    assert "Return upstream (parent branch)" in html
    assert "Return to main branch" in html
    assert "current: Main" in html
    assert "sidebar-scroll" in html
    assert "live response" not in html
    assert "Follow system" in html
    assert "theme-select" in html
    assert '<select id="theme-select">' not in html
    assert "color-select" in html
    assert '<select id="color-select">' not in html
    assert "Color" in html
    assert "Model selector" in html
    assert "Stop generation" in html
    assert "White" in html
    assert "Blue" in html
    assert "Mint" in html
    assert "Sunset" in html
    assert "Graphite" in html
    assert 'id="color-toggle"' in html
    assert 'data-preference-value="white"' in html
    assert "currentColor" in html
    assert "Clear input" in html
    assert 'id="stream-message" rows="1" aria-label="Message" placeholder="Start on the main thread, and create a branch only when you want to explore a separate direction."' in html
    assert "Keep the current thread focused here. Create a branch only when you want to split into a separate direction." in html
    assert ">Please analyze this topic, and use a branch only if needed.</textarea>" not in html
    assert "Issue demo token" not in html
    assert "Who am I" not in html
    assert "Tool feed" not in html
    assert "request failed" in html
    assert "load thread failed" in html
    assert "archive conversation failed" in html
    assert "archive branch failed" in html
    assert "activate branch failed" in html
    assert 'id="branch-policy-select"' not in html
    assert "renderArchivedBranches" in html
    assert "hidingActiveThread" in html
    assert "state.activeBranchMeta = payload.branch_meta || null;" in html
    assert "state.activeMergeProposal = payload.merge_proposal;" in html
    assert "if (payload.selected_model) {" in html
    assert "thinkingMode: payload.selected_thinking_mode || null" in html
    assert "proposal_overrides: {" in html
    assert "updateBranchCreationUi();" in html
    assert ".branch-card.clickable .branch-select" not in html
    assert "pendingBranchNodeForParent" not in html
    assert 'closest("[data-branch-action]")' in html
    assert 'Invalid branch tree payload.' in html
    assert "focus-agent-sidebar-collapsed" in html
    assert "focus-agent-tree-collapsed" not in html
    assert "message-code-block" in html
    assert "message-inline-code" in html
    assert "message-code-label" in html
    assert "code-copy-button" in html
    assert "buildMessageContent" in html
    assert "copyTextToClipboard" in html
    assert "message-actions" in html
    assert "message-action-button" in html
    assert "createMessageActionButton" in html
    assert "startEditingMessage" in html
    assert "cancelInlineMessageEdit" in html
    assert "submitInlineMessageEdit" in html
    assert "message-inline-editor" in html
    assert "message-inline-editor-input" in html
    assert "Send edited message" in html
    assert "Regenerate response" in html
    assert "Edit message" in html
    assert "Copy message" in html
    assert 'if (state.pendingBranch || isMergedReadOnlyThread()) {' in html
    assert 'if (isMergedReadOnlyThread()) {' in html
    assert "function isChatNearBottom(threshold = 48)" in html
    assert "function shouldAutoFollowChat({ forceScroll = false } = {})" in html
    assert 'function syncChatAutoFollowFromScroll()' in html
    assert "function pauseChatAutoFollow()" in html
    assert "function handleChatWheel(event)" in html
    assert "function handleChatTouchStart(event)" in html
    assert "function handleChatTouchMove(event)" in html
    assert "function handleChatTouchEnd()" in html
    assert "chatAutoFollow: true" in html
    assert "chatLastScrollTop: 0" in html
    assert "chatTouchY: null" in html
    assert "streamingResponseActive: false" in html
    assert 'const shouldFollow = shouldAutoFollowChat({ forceScroll });' in html
    assert 'beginChatTurn(message, { skipUserBubble: options.skipUserBubble === true });' in html
    assert "applyInlineMarkdown" in html
    assert "renderInlineMarkdown" in html
    assert "sanitizeMessageHref" in html
    assert "appendMarkdownBlock" in html
    assert 'const heading = lines[0].match(/^(#{1,6})\\s+(.*)$/);' in html
    assert 'const remaining = lines.slice(1).join("\\n").trim();' in html
    assert 'appendPlainText(parent, remaining);' in html
    assert "message-bubble h1" in html
    assert "message-bubble ul" in html
    assert "message-bubble blockquote" in html
    assert "message-bubble a" in html
    assert ".message-row:hover .message-actions" in html
    assert ".message-row.is-editing .message-actions" in html
    assert 'if (messageType === "system") {' in html
    assert 'createMessageBubble("system", content, `${isChineseUi() ? "系统" : "System"} · ${threadLabel}`, "success", false, {' in html
    assert 'createMessageBubble("system", `${title}: ${message}`, "System", "error", false, {' in html
    assert 'createMessageBubble("system", turnFailedBubbleText(message), isChineseUi() ? "系统" : "System", "error", false, {' in html
    assert "--system-bubble-text:#8E2344;" in html
    assert "--system-code-header-text:#A73358;" in html
    assert "--system-success-bubble-text:#17684B;" in html
    assert "--system-success-code-header-text:#1A7A59;" in html
    assert ".message-row.system.success .message-bubble" in html
    assert "linear-gradient(135deg, var(--user-bubble-top) 0%, var(--user-bubble-mid) 56%, var(--user-bubble-bottom) 100%)" in html
    assert '"JetBrains Mono", "SFMono-Regular"' in html
    assert "--gradient-brand:linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);" in html
    assert "padding:8px 12px;" in html
    assert "min-height:34px;" in html
    assert "max-height:136px;" in html
    assert 'function shouldSubmitComposerOnEnter(event)' in html
    assert '$("stream-message").addEventListener("keydown", (event) => {' in html
    assert 'function clearComposerInput({ focus = true } = {})' in html
    assert 'function syncComposerStreamingControls()' in html
    assert 'function stopStream()' in html
    assert 'function archivedConversationsLabel()' in html
    assert 'function archivedConversationOptionValue(rootThreadId)' in html
    assert 'parseArchivedConversationOptionValue(value)' in html
    assert 'async function createConversation(title = null)' in html
    assert 'async function archiveConversation(rootThreadId)' in html
    assert 'async function activateConversation(rootThreadId)' in html
    assert 'body: JSON.stringify(title ? { title } : {}),' in html
    assert 'async function createConversation(title = defaultConversationTitle((state.conversations?.length || 0) + 1))' not in html
    assert 'function resolveCompletedThreadStatePayload(rawPayload, requestedThreadId)' in html
    assert 'if (requestId !== state.threadLoadRequestId) {' in html
    assert 'if (requestId !== state.treeLoadRequestId) {' in html
    assert 'if (selectionRequestId !== state.conversationSelectionRequestId || state.activeConversationId !== rootThreadId) {' in html
    assert 'state.completedThreadStateById[completedThreadId] = payload.thread_state;' in html
    assert 'delete state.completedThreadStateById[resolvedThreadId];' in html
    assert '$("clear-stream").addEventListener("click", () => {' in html
    assert '$("stop-stream").addEventListener("click", stopStream);' in html
    assert 'sendButton.hidden = isStreaming;' in html
    assert 'stopButton.hidden = !isStreaming;' in html
    assert 'restoreInlineMessageBubble(session.bubble, session.originalText);' in html
    assert 'skipUserBubble: true' not in html
    assert 'event.stopPropagation();' in html
    assert 'thinkingMode: "enabled"' in html
    assert 'thinkingMode: "disabled"' in html
    assert 'clearComposerInput();' in html
    assert 'clearStreamView();' not in html
    assert 'thinking_mode: state.selectedThinkingMode || undefined' in html
    assert 'navigator.clipboard.writeText' in html
    assert 'document.execCommand("copy")' in html
    assert 'value.split(/\\n{2,}/)' in html
    assert 'replaceAll("\\n", "<br>")' in html
    assert 'codeText.replace(/\\n$/, "")' in html
    assert 'working.replace(/\\[([^\\]]+)\\]\\(([^\\s)]+)\\)/g' in html
    assert 'document.createElement("blockquote")' in html
    assert 'const shouldFollow = shouldAutoFollowChat();' in html
    assert 'if (shouldFollow) {' in html
    assert '$("chat-history").addEventListener("scroll", syncChatAutoFollowFromScroll, { passive: true });' in html
    assert '$("chat-history").addEventListener("wheel", handleChatWheel, { passive: true });' in html
    assert '$("chat-history").addEventListener("touchstart", handleChatTouchStart, { passive: true });' in html
    assert '$("chat-history").addEventListener("touchmove", handleChatTouchMove, { passive: true });' in html
    assert '$("chat-history").addEventListener("touchend", handleChatTouchEnd, { passive: true });' in html
    assert "if (state.streamingResponseActive) {" in html
    assert "state.streamingResponseActive = true;" in html
    assert "state.streamingResponseActive = false;" in html
    assert '\\n\\n[Waiting for resume decision]' in html
    assert 'textContent += "\n\n[Waiting for resume decision]"' not in html
    assert "<html lang=\"en\">" in html


def test_render_chat_app_html_supports_chinese():
    html = render_chat_app_html("zh")

    assert "Focus Agent 控制台" in html
    assert "带分支能力的研究对话界面" not in html
    assert "发送消息" in html
    assert "清空输入" in html
    assert "正在编辑消息" in html
    assert "修改后的内容会作为新一轮对话发送。" in html
    assert "编辑消息" in html
    assert "复制消息" in html
    assert "发送修改" in html
    assert "重新生成回复" in html
    assert "新建分支" in html
    assert "分支如何使用" in html
    assert "刷新分支树" in html
    assert "已归档分支" in html
    assert "暂无已归档分支。" in html
    assert "归档" in html
    assert "激活" in html
    assert "回到主分支" in html
    assert "回到上一层" in html
    assert "生成带回结论" in html
    assert 'id="open-skills"' not in html
    assert 'id="skills-modal"' not in html
    assert "重新生成结论" in html
    assert "带回目标" in html
    assert "开放问题" in html
    assert 'id="merge-proposal-open-questions"' in html
    assert "带回到上游（父分支）" in html
    assert "带回到主分支" in html
    assert "仅摘要：只带回结论摘要" in html
    assert "摘要 + 证据：带回摘要和关键证据引用" in html
    assert "指定 artifacts：只导入你勾选或填写的 artifacts" in html
    assert "推荐导入方式：" in html
    assert "focus-branch-tree" in html
    assert "branch-tree-panel" in html
    assert 'id="conversation-select"' in html
    assert 'id="conversation-rename"' in html
    assert 'id="conversation-archive"' in html
    assert 'data-tooltip="重命名对话"' in html
    assert 'data-tooltip="归档对话"' in html
    assert "正在加载对话..." in html
    assert "切换或新建对话" in html
    assert "重命名对话" in html
    assert "归档对话" in html
    assert "已归档对话" in html
    assert "重命名节点" in html
    assert "已合并分支不允许继续对话" in html
    assert "function mergedBranchReadOnlyLabel()" in html
    assert 'function isMergedReadOnlyThread(branchMeta = state.activeBranchMeta)' in html
    assert 'sidebarButton.disabled = isCreating || hitDepthLimit || isReadOnly;' in html
    assert 'toolbarButton.disabled = isCreating || hitDepthLimit || isReadOnly;' in html
    assert 'function syncComposerReadOnlyUi()' in html
    assert 'inputShell.classList.toggle("is-readonly", isReadOnly);' in html
    assert 'input.readOnly = isReadOnly;' in html
    assert 'sendButton.disabled = isReadOnly;' in html
    assert 'disabledLabel: isReadOnly ? mergedBranchReadOnlyLabel() : editMessageActionLabel(),' in html
    assert 'disabledLabel: isReadOnly ? mergedBranchReadOnlyLabel() : regenerateMessageActionLabel(),' in html
    assert "branch-graph" in html
    assert "tree-graph-legend" in html
    assert "branch-graph-root-label" in html
    assert "branch-graph-node-shell" in html
    assert "branch-node-detail" in html
    assert "renderGraphNode" in html
    assert "BRANCH_DETAIL_HIDE_DELAY_MS" in html
    assert "scheduleHideBranchDetail" in html
    assert 'branchDetailOverlay().addEventListener("focusout"' in html
    assert "mainTimelineLabel" in html
    assert "悬浮或点击任意节点查看分支详情，需要切换上下文时再打开它。" in html
    assert "brand-lockup" in html
    assert "chat-brand-lockup" in html
    assert "chat-logo-toggle" in html
    assert "brand-mark" in html
    assert "focus-agent-brand-accent" in html
    assert "focus-agent-chat-brand-accent" in html
    assert 'id="tree-branch-count-summary"' in html
    assert "进行中 0 · 已归档 0" in html
    assert 'id="sidebar-panel"' in html
    assert 'aria-controls="sidebar-panel"' in html
    assert "chat-header-primary-actions" in html
    assert "chat-header-nav" in html
    assert '<div class="chat-header-settings">' not in html
    assert "sidebar-settings" in html
    assert "chat-header-bottom" not in html
    assert "tree-title-row" in html
    assert ".tree-title-row h3" in html
    assert 'id="app-shell"' in html
    assert 'id="toggle-tree"' in html
    assert 'id="tree-panel-body"' in html
    assert "收起侧栏" in html
    assert "显示分支树" in html
    assert "传统 Chatbot 样式对话，左侧可切换分支。" not in html
    assert 'id="stream-status"' not in html
    assert 'id="status-feed"' not in html
    assert "agent-status-panel" not in html
    assert "agent-run-bubble" in html
    assert "createAgentActivityBubble" in html
    assert "ensureAssistantBubble" in html
    assert 'id="language-select"' in html
    assert '<select id="language-select">' not in html
    assert "语言" in html
    assert "English" in html
    assert "中文" in html
    assert "composer-footer-row" in html
    assert "composer-actions-row" in html
    assert "composer-model-row" in html
    assert html.index("composer-actions-row") < html.index("composer-model-row")
    assert 'id="composer-model-trigger"' in html
    assert 'id="composer-model-panel"' in html
    assert 'id="composer-model-list"' in html
    assert 'id="composer-model-trigger-logo"' in html
    assert 'id="stop-stream"' in html
    assert 'id="stop-stream-label"' in html
    assert "composer-model-thinking-toggle" in html
    assert 'id="composer-thinking-shell"' not in html
    assert "composer-model-logo-shell" in html
    assert "models.dev/logos/" in html
    assert "加载模型中..." in html
    assert "选择模型" in html
    assert "命令面板" in html
    assert "思考模式" in html
    assert "不支持思考切换" in html
    assert "panel-resizer" in html
    assert "info-trigger" in html
    assert "sidebar-scroll" in html
    assert "当前分支: 主线" in html
    assert "跟随系统" in html
    assert "浅色" in html
    assert "深色" in html
    assert "色系" in html
    assert "停止生成" in html
    assert "白色" in html
    assert "蓝色" in html
    assert "薄荷" in html
    assert "暮光" in html
    assert "石墨" in html
    assert "color-select" in html
    assert '<select id="theme-select">' not in html
    assert '<select id="color-select">' not in html
    assert 'id="color-toggle"' in html
    assert 'data-preference-value="white"' in html
    assert "currentColor" in html
    assert "current色系" not in html
    assert 'id="stream-message" rows="1" aria-label="消息" placeholder="先在主线程里展开对话，只有在需要单独探索一个方向时再创建分支。"' in html
    assert "这里先保持当前线程聚焦。只有当你想把问题拆到独立方向时，再创建分支。" in html
    assert ">请分析这个主题，只有在确实需要时才创建分支。</textarea>" not in html
    assert "实时回复" not in html
    assert "请求失败" in html
    assert "加载线程失败" in html
    assert "归档分支失败" in html
    assert "激活分支失败" in html
    assert 'id="branch-policy-select"' not in html
    assert "renderArchivedBranches" in html
    assert "render归档dBranches" not in html
    assert "--system-bubble-text:#8E2344;" in html
    assert "--system-code-header-text:#A73358;" in html
    assert "--system-success-bubble-text:#17684B;" in html
    assert "--system-success-code-header-text:#1A7A59;" in html
    assert ".message-row.system.success .message-bubble" in html
    assert "linear-gradient(135deg, var(--user-bubble-top) 0%, var(--user-bubble-mid) 56%, var(--user-bubble-bottom) 100%)" in html
    assert "min-height:34px;" in html
    assert "max-height:136px;" in html
    assert 'function shouldSubmitComposerOnEnter(event)' in html
    assert "hidingActiveThread" in html
    assert "state.activeBranchMeta = payload.branch_meta || null;" in html
    assert "state.activeMergeProposal = payload.merge_proposal;" in html
    assert "if (payload.selected_model) {" in html
    assert "thinkingMode: payload.selected_thinking_mode || null" in html
    assert "proposal_overrides: {" in html
    assert "updateBranchCreationUi();" in html
    assert "hidingActive线程" not in html
    assert ".branch-card.clickable .branch-select" not in html
    assert "pendingBranchNodeForParent" not in html
    assert 'closest("[data-branch-action]")' in html
    assert "Invalid branch tree payload." in html
    assert "focus-agent-sidebar-collapsed" in html
    assert "focus-agent-tree-collapsed" not in html
    assert "message-code-block" in html
    assert "message-inline-code" in html
    assert "message-code-label" in html
    assert "code-copy-button" in html
    assert "buildMessageContent" in html
    assert "copyTextToClipboard" in html
    assert "function isChatNearBottom(threshold = 48)" in html
    assert "function shouldAutoFollowChat({ forceScroll = false } = {})" in html
    assert 'function syncChatAutoFollowFromScroll()' in html
    assert "function pauseChatAutoFollow()" in html
    assert "function handleChatWheel(event)" in html
    assert "function handleChatTouchStart(event)" in html
    assert "function handleChatTouchMove(event)" in html
    assert "function handleChatTouchEnd()" in html
    assert "chatAutoFollow: true" in html
    assert "chatLastScrollTop: 0" in html
    assert "chatTouchY: null" in html
    assert "streamingResponseActive: false" in html
    assert 'const shouldFollow = shouldAutoFollowChat({ forceScroll });' in html
    assert 'beginChatTurn(message, { skipUserBubble: options.skipUserBubble === true });' in html
    assert "applyInlineMarkdown" in html
    assert "renderInlineMarkdown" in html
    assert "sanitizeMessageHref" in html
    assert "appendMarkdownBlock" in html
    assert 'const heading = lines[0].match(/^(#{1,6})\\s+(.*)$/);' in html
    assert 'const remaining = lines.slice(1).join("\\n").trim();' in html
    assert 'appendPlainText(parent, remaining);' in html
    assert 'if (state.pendingBranch || isMergedReadOnlyThread()) {' in html
    assert 'if (isMergedReadOnlyThread()) {' in html
    assert "message-bubble h1" in html
    assert "message-bubble ul" in html
    assert "message-bubble blockquote" in html
    assert "message-bubble a" in html
    assert 'navigator.clipboard.writeText' in html
    assert 'document.execCommand("copy")' in html
    assert 'value.split(/\\n{2,}/)' in html
    assert 'replaceAll("\\n", "<br>")' in html
    assert 'codeText.replace(/\\n$/, "")' in html
    assert 'working.replace(/\\[([^\\]]+)\\]\\(([^\\s)]+)\\)/g' in html
    assert 'document.createElement("blockquote")' in html
    assert 'const shouldFollow = shouldAutoFollowChat();' in html
    assert 'if (shouldFollow) {' in html
    assert '$("chat-history").addEventListener("scroll", syncChatAutoFollowFromScroll, { passive: true });' in html
    assert '$("chat-history").addEventListener("wheel", handleChatWheel, { passive: true });' in html
    assert '$("chat-history").addEventListener("touchstart", handleChatTouchStart, { passive: true });' in html
    assert '$("chat-history").addEventListener("touchmove", handleChatTouchMove, { passive: true });' in html
    assert '$("chat-history").addEventListener("touchend", handleChatTouchEnd, { passive: true });' in html
    assert "if (state.streamingResponseActive) {" in html
    assert "state.streamingResponseActive = true;" in html
    assert "state.streamingResponseActive = false;" in html
    assert "签发演示 Token" not in html
    assert "查看当前身份" not in html
    assert "工具事件流" not in html
    assert "messageTextOverrides" not in html
    assert "skipUserBubble: true" not in html
    assert '\\n\\n[等待继续执行决策]' in html
    assert 'textContent += "\n\n[等待继续执行决策]"' not in html
    assert "readErrorMessage" in html
    assert "readError消息" not in html
    assert "lastUserMessage" in html
    assert "lastUser消息" not in html
    assert "清空ed." not in html
    assert "<html lang=\"zh-CN\">" in html
