import {
  type PropsWithChildren,
  useCallback,
  useState,
} from "react";
import { useNavigate } from "@tanstack/react-router";

import { AppShellChatHeader } from "@/app/shell/app-shell-chat-header";
import { AppShellGlobalNavigation } from "@/app/shell/app-shell-global-navigation";
import { SidebarToggleIcon } from "@/app/shell/app-shell-icons";
import { AppShellSidebarBrand } from "@/app/shell/app-shell-sidebar-brand";
import { AppShellWorkspaceSidebar } from "@/app/shell/app-shell-workspace-sidebar";
import { useShellMergeProposalState } from "@/app/shell/hooks/use-shell-merge-status";
import { useShellNavTargets } from "@/app/shell/hooks/use-shell-nav-targets";
import { useShellPreferences } from "@/app/shell/hooks/use-shell-preferences";
import { useShellResizer } from "@/app/shell/hooks/use-shell-resizer";
import { useShellRouteState } from "@/app/shell/hooks/use-shell-route-state";
import { useShellTooltipState } from "@/app/shell/hooks/use-shell-tooltip";
import { MergeReviewModalHost } from "@/app/shell/merge-review-modal-host";
import { BranchTreePanel } from "@/features/branch-tree/branch-tree-panel";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";
import { useThreadState } from "@/features/thread/use-thread-state";
import {
  ShellUiProvider,
  useTransientShellStatus,
} from "@/app/shell/shell-ui-context";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import { SessionExitIcon } from "@/shared/ui/toolbar-icons";
import { tooltipProps } from "@/shared/ui/tooltip";

export function AppShell({ children }: PropsWithChildren) {
  const { logout, principal } = useFocusAgent();
  const navigate = useNavigate();
  const {
    conversationId,
    threadId,
    isAdminRoute,
    isAdminShell,
    isAgentGovernanceRoute,
    isAgentTeamRoute,
    isAgentWorkbenchShell,
    isChatRoute,
    isChatShell,
    isObservabilityRoute,
    isReviewRoute,
    isWorkspaceShell,
    pathname,
    rootThreadSearch,
    sessionId,
    shellMode,
    userId,
  } = useShellRouteState();
  const {
    activeAgentWorkbenchModule,
    adminNavTarget,
    agentTeamRootThreadId,
    chatNavTarget,
    lastAgentTeamTarget,
  } = useShellNavTargets({
    conversationId,
    isAdminRoute,
    isAgentGovernanceRoute,
    isAgentTeamRoute,
    isChatRoute,
    isObservabilityRoute,
    pathname,
    rootThreadSearch,
    sessionId,
    threadId,
    userId,
  });
  const {
    languagePreference,
    setLanguagePreference,
    themePreference,
    setThemePreference,
    colorPreference,
    setColorPreference,
    sidebarCollapsed,
    setSidebarCollapsed,
    sidebarWidth,
    setSidebarWidth,
    isChineseUi,
    shellStyle,
    selectedLanguage,
    selectedTheme,
    selectedColor,
    cycleLanguage,
    cycleTheme,
    cycleColor,
  } = useShellPreferences();
  const { handleResizerKeyDown, handleResizerPointerDown } = useShellResizer({
    sidebarCollapsed,
    sidebarWidth,
    setSidebarWidth,
  });
  const { tooltipRef, tooltipState, onShow: handleTooltipShow, onHide: handleTooltipHide } =
    useShellTooltipState();
  const {
    mergeProposalGeneration,
    markMergeProposalPreparing,
    markMergeProposalReady,
    markMergeProposalFailed,
    isMergeProposalPreparing,
    getMergeProposalError,
  } = useShellMergeProposalState();
  const [branchCreateBusy, setBranchCreateBusy] = useState(false);
  const [shellStatus, setShellStatus] = useTransientShellStatus();
  const { data: activeThreadState } = useThreadState(threadId);
  const { forkBranch } = useBranchActions({
    rootThreadId: conversationId,
    threadId,
  });
  const shellSidebarCollapsed = sidebarCollapsed;
  const currentMergeProposalState = threadId ? mergeProposalGeneration[threadId] : null;
  const currentMergeProposalStatus =
    currentMergeProposalState?.status === "ready" && currentMergeProposalState.showFloating
      ? {
          tone: "success" as const,
          text: isChineseUi ? "结论已生成" : "Conclusion generated",
        }
      : currentMergeProposalState?.status === "failed" && currentMergeProposalState.showFloating
        ? {
            tone: "danger" as const,
            text:
              currentMergeProposalState.error ||
              (isChineseUi ? "生成结论失败，请重新生成" : "Failed to generate conclusion. Please regenerate."),
          }
        : null;
  const principalName =
    principal?.user?.display_name ||
    principal?.user?.username ||
    principal?.user_id ||
    (isChineseUi ? "当前账号" : "Current account");
  const principalInitial = Array.from(principalName.trim())[0] || (isChineseUi ? "账" : "A");
  const currentAccountLabel = isChineseUi ? "当前" : "Me";
  const currentAccountTooltip = isChineseUi
    ? `当前账号：${principalName}`
    : `Current account: ${principalName}`;

  function toggleSidebar() {
    setSidebarCollapsed((value) => !value);
  }

  const selectedLanguageLabel = isChineseUi ? selectedLanguage.labelZh : selectedLanguage.labelEn;
  const selectedThemeLabel = isChineseUi ? selectedTheme.labelZh : selectedTheme.labelEn;
  const selectedColorLabel = isChineseUi ? selectedColor.labelZh : selectedColor.labelEn;
  const sidebarToggleLabel = sidebarCollapsed
    ? isChineseUi
      ? "展开侧栏"
      : "Show sidebar"
    : isChineseUi
      ? "收起侧栏"
      : "Collapse sidebar";

  async function createBranch(options?: { parentThreadId?: string }) {
    const parentThreadId = options?.parentThreadId ?? threadId ?? null;
    if (!conversationId || !parentThreadId || branchCreateBusy) return;
    setBranchCreateBusy(true);
    try {
      setShellStatus(
        {
          tone: "warn",
          text: languagePreference === "zh" ? "正在创建分支" : "Creating branch",
          display: "chat-floating",
        },
      );
      const record = await forkBranch({
        parentThreadId,
        language: languagePreference,
      });
      await navigate({
        to: "/c/$conversationId/t/$threadId",
        params: {
          conversationId: record.root_thread_id,
          threadId: record.child_thread_id,
        },
      });
      setShellStatus(
        {
          tone: "success",
          text: languagePreference === "zh" ? "分支已创建" : "Branch created",
          display: "chat-floating",
        },
        { autoClearMs: 2400 },
      );
    } catch (error) {
      setShellStatus(
        {
          tone: "danger",
          text:
            error instanceof Error
              ? error.message
              : languagePreference === "zh"
                ? "创建分支失败"
                : "Create branch failed",
          display: "chat-floating",
        },
      );
    } finally {
      setBranchCreateBusy(false);
    }
  }

  const closeMergeReviewModal = useCallback(async () => {
    if (!conversationId || !threadId) return;
    await navigate({
      to: "/c/$conversationId/t/$threadId",
      params: {
        conversationId,
        threadId,
      },
      replace: true,
    });
  }, [conversationId, navigate, threadId]);
  const handleCloseMergeReviewModal = useCallback(() => {
    void closeMergeReviewModal();
  }, [closeMergeReviewModal]);

  return (
    <ShellUiProvider
      value={{
        languagePreference,
        themePreference,
        colorPreference,
        setLanguagePreference,
        setThemePreference,
        setColorPreference,
        shellStatus,
        setShellStatus,
        createBranch,
        isCreatingBranch: branchCreateBusy,
        mergeProposalGeneration,
        markMergeProposalPreparing,
        markMergeProposalReady,
        markMergeProposalFailed,
        isMergeProposalPreparing,
        getMergeProposalError,
      }}
    >
      <div
        className={`fa-app-shell is-${shellMode}-shell ${shellSidebarCollapsed ? "is-sidebar-collapsed" : ""}`}
        style={shellStyle}
      >
        <aside className={`fa-sidebar-panel ${isWorkspaceShell ? "is-global-shell" : ""}`.trim()}>
          <AppShellSidebarBrand
            colorPreference={colorPreference}
            cycleColor={cycleColor}
            cycleLanguage={cycleLanguage}
            cycleTheme={cycleTheme}
            isChineseUi={isChineseUi}
            languagePreference={languagePreference}
            selectedColorLabel={selectedColorLabel}
            selectedLanguage={selectedLanguage}
            selectedLanguageLabel={selectedLanguageLabel}
            selectedThemeLabel={selectedThemeLabel}
            themePreference={themePreference}
            tooltipHandlers={{
              onBlur: handleTooltipHide,
              onFocus: handleTooltipShow,
              onMouseEnter: handleTooltipShow,
              onMouseLeave: handleTooltipHide,
            }}
            toggleSidebar={toggleSidebar}
          />
          <div className="fa-sidebar-scroll">
            {isChatShell ? (
              <BranchTreePanel />
            ) : (
              <AppShellWorkspaceSidebar
                activeAgentWorkbenchModule={activeAgentWorkbenchModule}
                agentTeamRootThreadId={agentTeamRootThreadId}
                isAgentWorkbenchShell={isAgentWorkbenchShell}
                isChineseUi={isChineseUi}
                pathname={pathname}
              />
            )}
          </div>
          <div className="fa-sidebar-dock">
            <AppShellGlobalNavigation
              adminNavTarget={adminNavTarget}
              agentTeamRootThreadId={agentTeamRootThreadId}
              chatNavTarget={chatNavTarget}
              isAdminRoute={isAdminRoute}
              isAgentWorkbenchShell={isAgentWorkbenchShell}
              isChatRoute={isChatRoute}
              isChineseUi={isChineseUi}
              lastAgentTeamTarget={lastAgentTeamTarget}
            />
            {principal ? (
              <div
                aria-label={currentAccountTooltip}
                className="fa-sidebar-account"
                role="group"
                {...tooltipProps(currentAccountTooltip)}
              >
                <span className="fa-sidebar-account-avatar" aria-hidden="true">
                  {principalInitial}
                </span>
                <div className="fa-sidebar-account-copy">
                  <strong>{currentAccountLabel}</strong>
                </div>
                <button
                  aria-label={isChineseUi ? "退出登录" : "Sign out"}
                  className="fa-sidebar-account-exit"
                  {...tooltipProps(isChineseUi ? "退出登录" : "Sign out")}
                  onBlur={handleTooltipHide}
                  onClick={() => void logout()}
                  onFocus={handleTooltipShow}
                  onMouseEnter={handleTooltipShow}
                  onMouseLeave={handleTooltipHide}
                  type="button"
                >
                  <SessionExitIcon />
                </button>
              </div>
            ) : null}
          </div>
        </aside>

        <div
          className="fa-panel-resizer"
          {...tooltipProps(isChineseUi ? "拖动调整左右栏宽度" : "Drag to resize panels")}
          onBlur={handleTooltipHide}
          onFocus={handleTooltipShow}
          onMouseEnter={handleTooltipShow}
          onMouseLeave={handleTooltipHide}
          onKeyDown={handleResizerKeyDown}
          onPointerDown={handleResizerPointerDown}
          role="separator"
          aria-label={isChineseUi ? "调整面板宽度" : "Resize panels"}
          aria-orientation="vertical"
          tabIndex={0}
        />

        <main className={`fa-chat-panel ${isWorkspaceShell ? "is-workspace-shell" : "is-chat-shell"}`}>
          {isWorkspaceShell ? (
            <button
              aria-label={sidebarToggleLabel}
              className={`fa-workspace-sidebar-toggle ${
                sidebarCollapsed ? "is-sidebar-collapsed" : ""
              }`.trim()}
              {...tooltipProps(sidebarToggleLabel)}
              onBlur={handleTooltipHide}
              onClick={toggleSidebar}
              onFocus={handleTooltipShow}
              onMouseEnter={handleTooltipShow}
              onMouseLeave={handleTooltipHide}
              type="button"
            >
              <SidebarToggleIcon collapsed={sidebarCollapsed} />
              <span>{sidebarToggleLabel}</span>
            </button>
          ) : null}

          {isChatShell ? (
            <AppShellChatHeader
              onOpenSidebar={() => setSidebarCollapsed(false)}
              onToggleSidebar={toggleSidebar}
              shellStatus={shellStatus}
              sidebarCollapsed={sidebarCollapsed}
              sidebarToggleLabel={sidebarToggleLabel}
              tooltipHandlers={{
                onBlur: handleTooltipHide,
                onFocus: handleTooltipShow,
                onMouseEnter: handleTooltipShow,
                onMouseLeave: handleTooltipHide,
              }}
            />
          ) : null}

          {currentMergeProposalStatus ? (
            <div className={`fa-shell-status-float is-${currentMergeProposalStatus.tone}`}>
              {currentMergeProposalStatus.text}
            </div>
          ) : null}

          {shellStatus?.display === "chat-floating" && !currentMergeProposalStatus ? (
            <div className={`fa-shell-status-float is-${shellStatus.tone}`}>{shellStatus.text}</div>
          ) : null}

          <div
            className={`fa-chat-main-body ${
              isAgentWorkbenchShell ? "is-agent-workbench-route" : ""
            } ${isAgentTeamRoute ? "is-agent-team-route" : ""} ${
              isAdminShell ? "is-admin-route" : ""
            }`.trim()}
          >
            {children}
          </div>
        </main>
      </div>

      <MergeReviewModalHost
        activeThreadState={activeThreadState}
        conversationId={conversationId}
        isChineseUi={isChineseUi}
        isReviewRoute={isReviewRoute}
        onClose={handleCloseMergeReviewModal}
        threadId={threadId}
      />

      {tooltipState ? (
        <div
          ref={tooltipRef}
          className="fa-toolbar-tooltip-overlay is-visible"
          style={{ left: `${tooltipState.left}px`, top: `${tooltipState.top}px` }}
        >
          {tooltipState.text}
        </div>
      ) : null}
    </ShellUiProvider>
  );
}
