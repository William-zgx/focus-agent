import type {
	BranchTreeNode,
	FocusAgentConversationSummary,
} from "@focus-agent/web-sdk";
import type { CSSProperties, Dispatch, SetStateAction } from "react";

import {
	branchStatusLabel,
	branchTotalTokens,
	formatTokenCount,
	roleColor,
	shouldShowArchivedSecondaryLine,
	statusAccentTone,
} from "@/features/branch-tree/branch-tree-helpers";
import { tooltipProps } from "@/shared/ui/tooltip";

type ArchivedSectionToggleProps = {
	ariaLabel: string;
	expanded: boolean;
	onExpandedChange: Dispatch<SetStateAction<boolean>>;
};

function ArchivedSectionToggle({
	ariaLabel,
	expanded,
	onExpandedChange,
}: ArchivedSectionToggleProps) {
	return (
		<button
			aria-expanded={expanded}
			aria-label={ariaLabel}
			className={`fa-tree-section-toggle ${expanded ? "" : "is-collapsed"}`.trim()}
			onClick={() => onExpandedChange((value) => !value)}
			type="button"
		>
			<svg aria-hidden="true" viewBox="0 0 20 20">
				<path
					d="m7 4 6 6-6 6"
					fill="none"
					stroke="currentColor"
					strokeLinecap="round"
					strokeLinejoin="round"
					strokeWidth="1.8"
				/>
			</svg>
		</button>
	);
}

type ArchivedConversationsSectionProps = {
	archivedConversations: FocusAgentConversationSummary[];
	archivedConversationsExpanded: boolean;
	isChineseUi: boolean;
	isWorking: boolean;
	onOpenConversation: (rootThreadId: string) => void;
	onRestoreConversation: (rootThreadId: string) => void;
	setArchivedConversationsExpanded: Dispatch<SetStateAction<boolean>>;
};

export function ArchivedConversationsSection({
	archivedConversations,
	archivedConversationsExpanded,
	isChineseUi,
	isWorking,
	onOpenConversation,
	onRestoreConversation,
	setArchivedConversationsExpanded,
}: ArchivedConversationsSectionProps) {
	return (
		<section className="fa-tree-card is-archived">
			<div className="fa-tree-section-header">
				<div className="fa-tree-section-title-group">
					<h3 className="fa-tree-subsection-title">
						{isChineseUi ? "已归档会话" : "Archived conversations"}
					</h3>
					<div className="fa-tree-summary">
						{isChineseUi
							? "归档后会从活动区移除，恢复后才会回来。"
							: "Archived conversations leave the active list until you restore them."}
					</div>
				</div>
				<ArchivedSectionToggle
					ariaLabel={
						isChineseUi
							? "展开或收起已归档会话"
							: "Toggle archived conversations"
					}
					expanded={archivedConversationsExpanded}
					onExpandedChange={setArchivedConversationsExpanded}
				/>
			</div>
			{archivedConversations.length && archivedConversationsExpanded ? (
				<div className="fa-archived-list is-conversations">
					{archivedConversations.map((conversation) => (
						<div
							className="fa-archived-item is-conversation"
							key={conversation.root_thread_id}
							style={
								{
									"--fa-branch-role-color": "#8FA7BF",
								} as CSSProperties
							}
						>
							<div className="fa-archived-item-head">
								<div className="fa-archived-item-copy">
									<div className="fa-archived-item-name">
										{conversation.title}
									</div>
									{shouldShowArchivedSecondaryLine(
										conversation.title,
										conversation.root_thread_id,
									) ? (
										<div className="fa-archived-item-id">
											{conversation.root_thread_id}
										</div>
									) : null}
								</div>
								<div className="fa-archived-item-toolbar">
									<div className="fa-tree-node-actions is-archived-actions">
										<button
											className="fa-branch-action-button"
											onClick={() =>
												onOpenConversation(conversation.root_thread_id)
											}
											type="button"
										>
											{isChineseUi ? "打开" : "Open"}
										</button>
										<button
											className="fa-branch-action-button"
											{...tooltipProps(
												isChineseUi
													? "恢复这个对话"
													: "Restore this conversation",
											)}
											disabled={isWorking}
											onClick={() =>
												onRestoreConversation(conversation.root_thread_id)
											}
											type="button"
										>
											{isChineseUi ? "恢复" : "Restore"}
										</button>
									</div>
								</div>
							</div>
						</div>
					))}
				</div>
			) : archivedConversations.length ? null : (
				<div className="fa-inline-notice fa-archived-empty">
					{isChineseUi ? "暂无已归档会话。" : "No archived conversations."}
				</div>
			)}
		</section>
	);
}

type ArchivedBranchesSectionProps = {
	archivedBranches: BranchTreeNode[];
	archivedBranchesExpanded: boolean;
	isChineseUi: boolean;
	isWorking: boolean;
	onOpenThread: (threadId: string) => void;
	onRestoreBranch: (node: BranchTreeNode) => void;
	setArchivedBranchesExpanded: Dispatch<SetStateAction<boolean>>;
};

export function ArchivedBranchesSection({
	archivedBranches,
	archivedBranchesExpanded,
	isChineseUi,
	isWorking,
	onOpenThread,
	onRestoreBranch,
	setArchivedBranchesExpanded,
}: ArchivedBranchesSectionProps) {
	return (
		<section className="fa-tree-card is-archived">
			<div className="fa-tree-section-header">
				<div className="fa-tree-section-title-group">
					<h3 className="fa-tree-subsection-title">
						{isChineseUi ? "已归档分支" : "Archived branches"}
					</h3>
					<div className="fa-tree-summary">
						{isChineseUi
							? "归档后会从分支树中移除，恢复后才会回来。"
							: "Archived branches leave the tree until you restore them."}
					</div>
				</div>
				<ArchivedSectionToggle
					ariaLabel={
						isChineseUi ? "展开或收起已归档分支" : "Toggle archived branches"
					}
					expanded={archivedBranchesExpanded}
					onExpandedChange={setArchivedBranchesExpanded}
				/>
			</div>
			{archivedBranches.length && archivedBranchesExpanded ? (
				<div className="fa-archived-list">
					{archivedBranches.map((node) => (
						<div
							className="fa-archived-item"
							key={node.thread_id}
							style={
								{
									"--fa-branch-role-color": roleColor(node.branch_role),
								} as CSSProperties
							}
						>
							<div className="fa-archived-item-head">
								<div className="fa-archived-item-copy">
									<div className="fa-archived-item-name">
										{node.branch_name}
									</div>
									{shouldShowArchivedSecondaryLine(
										node.branch_name,
										node.thread_id,
									) ? (
										<div className="fa-archived-item-id">{node.thread_id}</div>
									) : null}
								</div>
								<div className="fa-archived-item-toolbar">
									<div className="fa-archived-item-token">
										{formatTokenCount(branchTotalTokens(node))} tokens
									</div>
									<div
										className={`fa-archived-item-status is-archived ${statusAccentTone(
											node.branch_status,
										)}`.trim()}
									>
										{branchStatusLabel(node.branch_status, isChineseUi)}
									</div>
									<div className="fa-tree-node-actions is-archived-actions">
										<button
											className="fa-branch-action-button"
											onClick={() => onOpenThread(node.thread_id)}
											type="button"
										>
											{isChineseUi ? "打开" : "Open"}
										</button>
										<button
											className="fa-branch-action-button"
											{...tooltipProps(
												isChineseUi ? "恢复这个分支" : "Restore this branch",
											)}
											disabled={isWorking}
											onClick={() => onRestoreBranch(node)}
											type="button"
										>
											{isChineseUi ? "恢复" : "Restore"}
										</button>
									</div>
								</div>
							</div>
						</div>
					))}
				</div>
			) : archivedBranches.length ? null : (
				<div className="fa-inline-notice fa-archived-empty">
					{isChineseUi ? "暂无已归档分支。" : "No archived branches."}
				</div>
			)}
		</section>
	);
}
