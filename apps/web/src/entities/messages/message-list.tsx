import {
	safeVisibleText,
	type FocusAgentBranchActionProposal,
	type FocusAgentBranchDecisionSummary,
	type FocusAgentStreamStep,
	type FocusAgentToolApprovalInterrupt,
	type RunFailedPayload,
} from "@focus-agent/web-sdk";
import { useMemo } from "react";

import { BranchActionCard } from "./message-list-branch-action-card";
import {
	MessageRow,
	StreamingReplyRow,
	SystemFailureRow,
} from "./message-list-message-row";
import { AgentRunBubble } from "./message-list-streaming-bubble";
import { ToolApprovalCard } from "./message-list-tool-approval-card";
import { ToolActivityCard } from "./message-list-tool-activity-card";
import {
	buildTranscriptItems,
	normalizeMessageType,
	normalizeText,
	type TranscriptDisplayMessage,
	type TranscriptItem,
} from "./message-transcript";

type MessageListRenderItem =
	| { kind: "branch-action"; action: FocusAgentBranchActionProposal }
	| { kind: "transcript"; item: TranscriptItem };

interface MessageListProps {
	isReadOnly?: boolean;
	isStreaming?: boolean;
	messages: Array<Record<string, unknown>>;
	assistantMessage?: string | null;
	streamVisibleText?: string;
	streamReasoningText?: string;
	streamProcessingSteps?: FocusAgentStreamStep[];
	streamFailed?: RunFailedPayload;
	branchActions?: FocusAgentBranchActionProposal[];
	branchDecisionSummary?: FocusAgentBranchDecisionSummary | null;
	branchActionErrors?: Record<string, string>;
	branchActionInFlightId?: string | null;
	toolApprovalInterrupts?: FocusAgentToolApprovalInterrupt[];
	toolApprovalError?: string;
	toolApprovalErrorId?: string | null;
	toolApprovalInFlightId?: string | null;
	isChineseUi?: boolean;
	onEditMessage?: (message: { id: string; content: string }) => void;
	onExecuteBranchAction?: (action: FocusAgentBranchActionProposal) => void;
	onContinueCurrentBranchAction?: (
		action: FocusAgentBranchActionProposal,
	) => void;
	onDismissBranchAction?: (action: FocusAgentBranchActionProposal) => void;
	onDecideToolApproval?: (
		interrupt: FocusAgentToolApprovalInterrupt,
		approved: boolean,
	) => void;
}

export function MessageList({
	isReadOnly = false,
	isStreaming = false,
	messages,
	assistantMessage,
	streamVisibleText,
	streamReasoningText,
	streamProcessingSteps,
	streamFailed,
	branchActions = [],
	branchDecisionSummary = null,
	branchActionErrors = {},
	branchActionInFlightId = null,
	toolApprovalInterrupts = [],
	toolApprovalError = "",
	toolApprovalErrorId = null,
	toolApprovalInFlightId = null,
	isChineseUi = false,
	onEditMessage,
	onExecuteBranchAction,
	onContinueCurrentBranchAction,
	onDismissBranchAction,
	onDecideToolApproval,
}: MessageListProps) {
	const transcriptItems = useMemo(
		() => buildTranscriptItems(messages, assistantMessage),
		[assistantMessage, messages],
	);
	const safeStreamVisibleText = safeVisibleText(streamVisibleText ?? "");
	const visibleStreamReply = normalizeText(safeStreamVisibleText)
		? safeStreamVisibleText
		: "";
	const latestBranchDecision = branchDecisionSummary?.latest_decision ?? null;
	const renderItems = useMemo(
		() => buildMessageListRenderItems(transcriptItems, branchActions),
		[branchActions, transcriptItems],
	);

	return (
		<div className="fa-message-list">
			{renderItems.map((renderItem) => {
				if (renderItem.kind === "branch-action") {
					const action = renderItem.action;
					return (
						<BranchActionCard
							key={action.action_id}
							action={action}
							isChineseUi={isChineseUi}
							isReadOnly={isReadOnly || isStreaming}
							errorMessage={branchActionErrors[action.action_id]}
							isBusy={branchActionInFlightId === action.action_id}
							sourceDecision={
								latestBranchDecision?.decision_id === action.source_decision_id
									? latestBranchDecision
									: null
							}
							onExecute={onExecuteBranchAction}
							onContinueCurrent={onContinueCurrentBranchAction}
							onDismiss={onDismissBranchAction}
						/>
					);
				}

				const item = renderItem.item;
				if (item.kind === "tool-activity") {
					return (
						<ToolActivityCard
							key={item.id}
							activity={item}
							isChineseUi={isChineseUi}
						/>
					);
				}

				return (
					<MessageRow
						key={item.id}
						content={item.content}
						id={item.id}
						isChineseUi={isChineseUi}
						isReadOnly={isReadOnly}
						onEditMessage={onEditMessage}
						totalTokens={item.totalTokens}
						type={item.type}
					/>
				);
			})}

			{toolApprovalInterrupts.map((interrupt) => (
				<ToolApprovalCard
					key={interrupt.tool_call_id}
					interrupt={interrupt}
					isBusy={toolApprovalInFlightId === interrupt.tool_call_id}
					isChineseUi={isChineseUi}
					isReadOnly={isReadOnly}
					errorMessage={
						toolApprovalErrorId === interrupt.tool_call_id
							? toolApprovalError
							: ""
					}
					onDecide={onDecideToolApproval}
				/>
			))}

			<AgentRunBubble
				isStreaming={isStreaming}
				isChineseUi={isChineseUi}
				processingSteps={streamProcessingSteps}
				reasoningText={streamReasoningText}
				visibleText={visibleStreamReply}
			/>

			{visibleStreamReply ? (
				<StreamingReplyRow
					isChineseUi={isChineseUi}
					text={visibleStreamReply}
				/>
			) : null}

			{streamFailed ? (
				<SystemFailureRow failed={streamFailed} isChineseUi={isChineseUi} />
			) : null}
		</div>
	);
}

function buildMessageListRenderItems(
	transcriptItems: TranscriptItem[],
	branchActions: FocusAgentBranchActionProposal[],
): MessageListRenderItem[] {
	if (branchActions.length === 0) {
		return transcriptItems.map((item) => ({ kind: "transcript", item }));
	}

	const actionBuckets = new Map<number, FocusAgentBranchActionProposal[]>();
	for (const action of [...branchActions].sort(compareBranchActions)) {
		const insertionIndex = branchActionInsertionIndex(transcriptItems, action);
		const bucket = actionBuckets.get(insertionIndex) ?? [];
		bucket.push(action);
		actionBuckets.set(insertionIndex, bucket);
	}

	const renderItems: MessageListRenderItem[] = [];
	for (let index = 0; index <= transcriptItems.length; index += 1) {
		for (const action of actionBuckets.get(index) ?? []) {
			renderItems.push({ kind: "branch-action", action });
		}
		const item = transcriptItems[index];
		if (item) {
			renderItems.push({ kind: "transcript", item });
		}
	}
	return renderItems;
}

function branchActionInsertionIndex(
	transcriptItems: TranscriptItem[],
	action: FocusAgentBranchActionProposal,
) {
	const handoffMessage = normalizeText(action.handoff_message).replace(
		/\s+/g,
		" ",
	);
	if (!handoffMessage) {
		return transcriptItems.length;
	}

	let anchorIndex = -1;
	for (let index = 0; index < transcriptItems.length; index += 1) {
		const item = transcriptItems[index];
		if (!isHumanMessage(item)) continue;
		const itemContent = normalizeText(item.content).replace(/\s+/g, " ");
		if (itemContent === handoffMessage) {
			anchorIndex = index;
		}
	}
	if (anchorIndex < 0) {
		return transcriptItems.length;
	}

	let insertionIndex = anchorIndex + 1;
	while (insertionIndex < transcriptItems.length) {
		if (isHumanMessage(transcriptItems[insertionIndex])) break;
		insertionIndex += 1;
	}
	return insertionIndex;
}

function isHumanMessage(
	item: TranscriptItem,
): item is TranscriptDisplayMessage {
	return (
		item.kind === "message" && normalizeMessageType(item.type) === "human"
	);
}

function compareBranchActions(
	left: FocusAgentBranchActionProposal,
	right: FocusAgentBranchActionProposal,
) {
	return branchActionTime(left) - branchActionTime(right);
}

function branchActionTime(action: FocusAgentBranchActionProposal) {
	const timestamp = Date.parse(action.created_at);
	return Number.isFinite(timestamp) ? timestamp : 0;
}
