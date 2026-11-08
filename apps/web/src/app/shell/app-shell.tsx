import {
	type PropsWithChildren,
	useCallback,
	useEffect,
	useState,
} from "react";
import { useNavigate } from "@tanstack/react-router";

import { AppShellChatHeader } from "@/app/shell/app-shell-chat-header";
import { AppShellGlobalNavigation } from "@/app/shell/app-shell-global-navigation";
import { SidebarToggleIcon } from "@/app/shell/app-shell-icons";
import { AppShellSidebarBrand } from "@/app/shell/app-shell-sidebar-brand";
import { AppShellWorkspaceSidebar } from "@/app/shell/app-shell-workspace-sidebar";
import {
	getSidebarViewportMax,
	SIDEBAR_WIDTH_MIN,
} from "@/app/shell/app-shell-config";
import { useShellMergeProposalState } from "@/app/shell/hooks/use-shell-merge-status";
import { useShellNavTargets } from "@/app/shell/hooks/use-shell-nav-targets";
import { useShellPreferences } from "@/app/shell/hooks/use-shell-preferences";
import { useShellResizer } from "@/app/shell/hooks/use-shell-resizer";
import { useShellRouteState } from "@/app/shell/hooks/use-shell-route-state";
import { useShellTooltipState } from "@/app/shell/hooks/use-shell-tooltip";
import { MergeReviewModalHost } from "@/app/shell/merge-review-modal-host";
import {
	BranchForkDialog,
	type BranchForkRequest,
	type BranchForkSubmission,
} from "@/features/branch-tree/branch-fork-dialog";
import { findNode } from "@/features/branch-tree/branch-tree-helpers";
import { BranchTreePanel } from "@/features/branch-tree/branch-tree-panel";
import { setPendingBranchGoal } from "@/features/branch-tree/pending-branch-goal";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";
import { useBranchTree } from "@/features/branch-tree/use-branch-tree";
import { useThreadState } from "@/features/thread/use-thread-state";
import {
	ShellUiProvider,
	useTransientShellStatus,
} from "@/app/shell/shell-ui-context";
import { appEnv } from "@/shared/config/env";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import { SessionExitIcon } from "@/shared/ui/toolbar-icons";
import { tooltipProps } from "@/shared/ui/tooltip";

export function AppShell({ children }: PropsWithChildren) {
	const { logout, principal } = useFocusAgent();
	const navigate = useNavigate();
	const {
		conversationId,
		threadId,
		isAdminShell,
		isAgentGovernanceRoute,
		isAgentMemoryRoute,
		isAgentWorkbenchShell,
		isChatRoute,
		isChatShell,
		isObservabilityRoute,
		isProductivityRoute,
		isReviewRoute,
		isWorkspaceShell,
		pathname,
		shellMode,
	} = useShellRouteState();
	const { activeAgentWorkbenchModule, chatNavTarget } = useShellNavTargets({
		conversationId,
		isAgentGovernanceRoute,
		isAgentMemoryRoute,
		isObservabilityRoute,
		isProductivityRoute,
		threadId,
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
	const {
		tooltipRef,
		tooltipState,
		onShow: handleTooltipShow,
		onHide: handleTooltipHide,
	} = useShellTooltipState();
	const {
		mergeProposalGeneration,
		markMergeProposalPreparing,
		markMergeProposalReady,
		markMergeProposalFailed,
		isMergeProposalPreparing,
		getMergeProposalError,
	} = useShellMergeProposalState();
	const [branchCreateBusy, setBranchCreateBusy] = useState(false);
	const [forkRequest, setForkRequest] = useState<BranchForkRequest | null>(
		null,
	);
	const [forkError, setForkError] = useState<string | null>(null);
	const { data: branchTreeData } = useBranchTree(threadId || conversationId);
	const [shellStatus, setShellStatus] = useTransientShellStatus();
	const { data: activeThreadState } = useThreadState(threadId);
	const { forkBranch } = useBranchActions({
		rootThreadId: conversationId,
		threadId,
	});
	const shellSidebarCollapsed = sidebarCollapsed;
	const currentMergeProposalState = threadId
		? mergeProposalGeneration[threadId]
		: null;
	const currentMergeProposalStatus =
		currentMergeProposalState?.status === "ready" &&
		currentMergeProposalState.showFloating
			? {
					tone: "success" as const,
					text: isChineseUi ? "结论已生成" : "Conclusion generated",
				}
			: currentMergeProposalState?.status === "failed" &&
					currentMergeProposalState.showFloating
				? {
						tone: "danger" as const,
						text:
							currentMergeProposalState.error ||
							(isChineseUi
								? "生成结论失败，请重新生成"
								: "Failed to generate conclusion. Please regenerate."),
					}
				: null;
	const principalName =
		principal?.user?.display_name ||
		principal?.user?.username ||
		principal?.user_id ||
		(isChineseUi ? "当前账号" : "Current account");
	const principalInitial =
		Array.from(principalName.trim())[0] || (isChineseUi ? "账" : "A");
	const currentAccountLabel = isChineseUi ? "当前" : "Me";
	const currentAccountTooltip = isChineseUi
		? `当前账号：${principalName}`
		: `Current account: ${principalName}`;

	function toggleSidebar() {
		setSidebarCollapsed((value) => !value);
	}

	useEffect(() => {
		if (!pathname) return;
		if (window.matchMedia("(max-width: 900px)").matches) {
			setSidebarCollapsed(true);
		}
	}, [pathname, setSidebarCollapsed]);

	const selectedLanguageLabel = isChineseUi
		? selectedLanguage.labelZh
		: selectedLanguage.labelEn;
	const selectedThemeLabel = isChineseUi
		? selectedTheme.labelZh
		: selectedTheme.labelEn;
	const selectedColorLabel = isChineseUi
		? selectedColor.labelZh
		: selectedColor.labelEn;
	const sidebarToggleLabel = sidebarCollapsed
		? isChineseUi
			? "展开侧栏"
			: "Show sidebar"
		: isChineseUi
			? "收起侧栏"
			: "Collapse sidebar";

	async function createBranch(options?: {
		parentThreadId?: string;
		goalDraft?: string;
		forkAtMessageId?: string;
	}) {
		const parentThreadId = options?.parentThreadId ?? threadId ?? null;
		if (!conversationId || !parentThreadId || branchCreateBusy) return;
		const parentLabel =
			findNode(branchTreeData?.root, parentThreadId)?.branch_name ||
			(parentThreadId === threadId
				? activeThreadState?.branch_meta?.branch_name
				: undefined);
		setForkError(null);
		setForkRequest({
			parentThreadId,
			parentLabel,
			goalDraft: options?.goalDraft,
			forkAtMessageId: options?.forkAtMessageId,
		});
	}

	const closeForkDialog = useCallback(() => {
		setForkRequest(null);
		setForkError(null);
	}, []);

	async function submitForkDialog(submission: BranchForkSubmission) {
		const request = forkRequest;
		if (!conversationId || !request || branchCreateBusy) return;
		setBranchCreateBusy(true);
		setForkError(null);
		try {
			const record = await forkBranch({
				parentThreadId: request.parentThreadId,
				forkAtMessageId: request.forkAtMessageId,
				branchName: submission.branchName,
				branchRole: submission.branchRole,
				nameSource: submission.goal,
				language: languagePreference,
			});
			setForkRequest(null);
			if (submission.goal) {
				setPendingBranchGoal(record.child_thread_id, submission.goal);
			}
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
			setForkError(
				error instanceof Error
					? error.message
					: languagePreference === "zh"
						? "创建分支失败"
						: "Create branch failed",
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
				{shellSidebarCollapsed ? null : (
					<button
						aria-label={isChineseUi ? "关闭侧栏" : "Close sidebar"}
						className="fa-sidebar-scrim"
						onClick={() => setSidebarCollapsed(true)}
						type="button"
					/>
				)}
				<aside
					className={`fa-sidebar-panel ${isWorkspaceShell ? "is-global-shell" : ""}`.trim()}
					aria-hidden={shellSidebarCollapsed}
				>
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
						) : appEnv.useLocalRuntime && isAdminShell ? null : (
							<AppShellWorkspaceSidebar
								activeAgentWorkbenchModule={activeAgentWorkbenchModule}
								isAgentWorkbenchShell={isAgentWorkbenchShell}
								isChineseUi={isChineseUi}
								pathname={pathname}
							/>
						)}
					</div>
					<div className="fa-sidebar-dock">
						<AppShellGlobalNavigation
							chatNavTarget={chatNavTarget}
							isChatRoute={isChatRoute}
							isChineseUi={isChineseUi}
							isProductivityRoute={isProductivityRoute}
						/>
						{principal && !appEnv.useLocalRuntime ? (
							<fieldset
								aria-label={currentAccountTooltip}
								className="fa-sidebar-account"
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
							</fieldset>
						) : null}
					</div>
				</aside>

				<section
					aria-label={isChineseUi ? "面板宽度调整" : "Panel width adjustment"}
					style={{ display: "contents" }}
				>
					<hr
						className="fa-panel-resizer"
						{...tooltipProps(
							isChineseUi ? "拖动调整左右栏宽度" : "Drag to resize panels",
						)}
						onBlur={handleTooltipHide}
						onFocus={handleTooltipShow}
						onMouseEnter={handleTooltipShow}
						onMouseLeave={handleTooltipHide}
						onKeyDown={handleResizerKeyDown}
						onPointerDown={handleResizerPointerDown}
						aria-label={isChineseUi ? "调整面板宽度" : "Resize panels"}
						aria-orientation="vertical"
						aria-valuemin={SIDEBAR_WIDTH_MIN}
						aria-valuemax={getSidebarViewportMax()}
						aria-valuenow={sidebarWidth}
						tabIndex={0}
					/>
				</section>

				<main
					className={`fa-chat-panel ${isWorkspaceShell ? "is-workspace-shell" : "is-chat-shell"}`}
				>
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
						<div
							className={`fa-shell-status-float is-${currentMergeProposalStatus.tone}`}
						>
							{currentMergeProposalStatus.text}
						</div>
					) : null}

					{shellStatus?.display === "chat-floating" &&
					!currentMergeProposalStatus ? (
						<div className={`fa-shell-status-float is-${shellStatus.tone}`}>
							{shellStatus.text}
						</div>
					) : null}

					<div
						className={`fa-chat-main-body ${
							isAgentWorkbenchShell ? "is-agent-workbench-route" : ""
						} ${isAdminShell ? "is-admin-route" : ""}`.trim()}
					>
						{children}
					</div>
				</main>
			</div>

			<BranchForkDialog
				errorMessage={forkError}
				isChineseUi={isChineseUi}
				isSubmitting={branchCreateBusy}
				onClose={closeForkDialog}
				onSubmit={(submission) => void submitForkDialog(submission)}
				request={forkRequest}
			/>

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
					style={{
						left: `${tooltipState.left}px`,
						top: `${tooltipState.top}px`,
					}}
				>
					{tooltipState.text}
				</div>
			) : null}
		</ShellUiProvider>
	);
}
