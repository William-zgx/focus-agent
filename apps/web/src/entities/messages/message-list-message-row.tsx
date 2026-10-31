import type { RunFailedPayload } from "@focus-agent/web-sdk";

import {
	branchGoalDraftFromMessage,
	bubbleClass,
	failureText,
	messageLayoutClass,
	roleClass,
	roleLabel,
	tokenUsageLabel,
} from "./message-list-helpers";
import type { BranchImportView } from "./message-branch-import";
import {
	BranchImportCard,
	type ThreadLinks,
} from "./message-branch-import-card";
import { MessageMarkdown } from "./message-markdown";
import { MessageActions } from "./message-list-actions";
import { normalizeMessageType } from "./message-transcript";

export function branchImportCardDomId(messageId: string) {
	return `fa-branch-import-${messageId}`;
}

export function MessageRow({
	branchImport,
	content,
	id,
	isHighlighted = false,
	isChineseUi,
	isReadOnly,
	onBranchFromMessage,
	onEditMessage,
	threadLinks,
	totalTokens,
	type,
}: {
	branchImport?: BranchImportView | null;
	content: string;
	id: string;
	isHighlighted?: boolean;
	isChineseUi: boolean;
	isReadOnly: boolean;
	onBranchFromMessage?: (message: { id: string; content: string }) => void;
	onEditMessage?: (message: { id: string; content: string }) => void;
	threadLinks?: ThreadLinks | null;
	totalTokens?: number;
	type: unknown;
}) {
	if (branchImport) {
		return (
			<div className={messageLayoutClass(type)}>
				<div className="fa-message-stack">
					<BranchImportCard
						id={branchImportCardDomId(id)}
						isChineseUi={isChineseUi}
						isHighlighted={isHighlighted}
						threadLinks={threadLinks}
						view={branchImport}
					/>
				</div>
			</div>
		);
	}

	const messageType = normalizeMessageType(type);
	const isHuman = messageType === "human";
	const canBranchFrom = isHuman || messageType === "ai";
	return (
		<div className={messageLayoutClass(type)}>
			<div className="fa-message-stack">
				<div className="fa-message-head">
					<div className={roleClass(type)}>{roleLabel(type, isChineseUi)}</div>
					{totalTokens ? (
						<div className="fa-message-usage-meta">
							{tokenUsageLabel(totalTokens, isChineseUi)}
						</div>
					) : null}
				</div>
				<div className={bubbleClass(type)}>
					<div className="fa-message-content">
						<MessageMarkdown isChineseUi={isChineseUi} text={content} />
					</div>
				</div>
				<MessageActions
					content={content}
					isChineseUi={isChineseUi}
					isReadOnly={isReadOnly}
					onBranch={
						canBranchFrom && onBranchFromMessage
							? () =>
									onBranchFromMessage({
										id,
										content: branchGoalDraftFromMessage(
											content,
											isHuman,
											isChineseUi,
										),
									})
							: null
					}
					onEdit={
						isHuman && onEditMessage
							? () => onEditMessage({ id, content })
							: null
					}
				/>
			</div>
		</div>
	);
}

export function StreamingReplyRow({
	isChineseUi,
	text,
}: {
	isChineseUi: boolean;
	text: string;
}) {
	return (
		<div className="fa-message-row is-assistant assistant">
			<div className="fa-message-stack">
				<div className="fa-message-head">
					<div className="fa-message-role fa-message-meta is-streaming">
						{isChineseUi ? "输出中" : "Streaming"}
					</div>
				</div>
				<div className="fa-message-bubble is-streaming">
					<div className="fa-message-content">
						<MessageMarkdown isChineseUi={isChineseUi} text={text} />
					</div>
				</div>
			</div>
		</div>
	);
}

export function SystemFailureRow({
	failed,
	isChineseUi,
}: {
	failed: RunFailedPayload;
	isChineseUi: boolean;
}) {
	return (
		<div className="fa-message-row is-system system">
			<div className="fa-message-stack">
				<div className="fa-message-head">
					<div className="fa-message-role fa-message-meta is-system">
						{isChineseUi ? "系统" : "System"}
					</div>
				</div>
				<div className="fa-message-bubble is-system">
					<div className="fa-message-content">
						<MessageMarkdown
							isChineseUi={isChineseUi}
							text={failureText(failed, isChineseUi)}
						/>
					</div>
				</div>
			</div>
		</div>
	);
}
