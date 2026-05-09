import type { RunFailedPayload } from "@focus-agent/web-sdk";

import {
	bubbleClass,
	failureText,
	messageLayoutClass,
	roleClass,
	roleLabel,
	tokenUsageLabel,
} from "./message-list-helpers";
import { MessageMarkdown } from "./message-markdown";
import { MessageActions } from "./message-list-actions";
import { normalizeMessageType } from "./message-transcript";

export function MessageRow({
	content,
	id,
	isChineseUi,
	isReadOnly,
	onEditMessage,
	totalTokens,
	type,
}: {
	content: string;
	id: string;
	isChineseUi: boolean;
	isReadOnly: boolean;
	onEditMessage?: (message: { id: string; content: string }) => void;
	totalTokens?: number;
	type: unknown;
}) {
	const isHuman = normalizeMessageType(type) === "human";
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
