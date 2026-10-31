import {
	safeVisibleText,
	type FocusAgentAskUserQuestionAnswer,
	type FocusAgentAskUserQuestionInterrupt,
	type FocusAgentBranchActionExecuteRequest,
	type FocusAgentBranchActionProposal,
	type FocusAgentBranchDecisionSummary,
	type FocusAgentMergeQueueEntry,
	type FocusAgentStreamStep,
	type FocusAgentToolApprovalInterrupt,
	type RunFailedPayload,
} from "@focus-agent/web-sdk";
import { useEffect, useMemo, useState } from "react";

import { AskUserQuestionCard } from "./message-list-ask-user-question-card";
import {
	clearPendingBranchImportHighlight,
	matchPendingBranchImportHighlight,
	withMergeQueueDetails,
} from "./message-branch-import";
import type { ThreadLinks } from "./message-branch-import-card";
import { BranchActionCard } from "./message-list-branch-action-card";
import {
	branchImportCardDomId,
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
	askUserQuestionInterrupts?: FocusAgentAskUserQuestionInterrupt[];
	askUserQuestionError?: string;
	askUserQuestionErrorId?: string | null;
	askUserQuestionInFlightId?: string | null;
	isChineseUi?: boolean;
	onBranchFromMessage?: (message: { id: string; content: string }) => void;
	onEditMessage?: (message: { id: string; content: string }) => void;
	onExecuteBranchAction?: (
		action: FocusAgentBranchActionProposal,
		overrides?: FocusAgentBranchActionExecuteRequest,
	) => void;
	onDismissBranchAction?: (action: FocusAgentBranchActionProposal) => void;
	onReviewMergeBranchAction?: (action: FocusAgentBranchActionProposal) => void;
	onDecideToolApproval?: (
		interrupt: FocusAgentToolApprovalInterrupt,
		approved: boolean,
	) => void;
	onSubmitAskUserQuestion?: (
		interrupt: FocusAgentAskUserQuestionInterrupt,
		answers: FocusAgentAskUserQuestionAnswer[],
	) => void;
	threadLinks?: ThreadLinks | null;
	/** Target-thread merge queue; enriches import notices with extra detail. */
	mergeQueue?: FocusAgentMergeQueueEntry[];
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
	askUserQuestionInterrupts = [],
	askUserQuestionError = "",
	askUserQuestionErrorId = null,
	askUserQuestionInFlightId = null,
	isChineseUi = false,
	onBranchFromMessage,
	onEditMessage,
	onExecuteBranchAction,
	onDismissBranchAction,
	onReviewMergeBranchAction,
	onDecideToolApproval,
	onSubmitAskUserQuestion,
	threadLinks = null,
	mergeQueue,
}: MessageListProps) {
	const isCurrentTurnActive =
		isStreaming ||
		toolApprovalInterrupts.length > 0 ||
		askUserQuestionInterrupts.length > 0;
	const transcriptItems = useMemo(
		() =>
			buildTranscriptItems(messages, assistantMessage, {
				isCurrentTurnActive,
			}),
		[assistantMessage, isCurrentTurnActive, messages],
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
	const highlightedImportId = useBranchImportHighlight(transcriptItems);

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
							onDismiss={onDismissBranchAction}
							onReviewMerge={onReviewMergeBranchAction}
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
						branchImport={
							item.branchImport
								? withMergeQueueDetails(item.branchImport, mergeQueue)
								: null
						}
						content={item.content}
						id={item.id}
						isChineseUi={isChineseUi}
						isHighlighted={highlightedImportId === item.id}
						isReadOnly={isReadOnly}
						onBranchFromMessage={onBranchFromMessage}
						onEditMessage={onEditMessage}
						threadLinks={threadLinks}
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

			{askUserQuestionInterrupts.map((interrupt) => (
				<AskUserQuestionCard
					key={interrupt.tool_call_id}
					interrupt={interrupt}
					isBusy={askUserQuestionInFlightId === interrupt.tool_call_id}
					isChineseUi={isChineseUi}
					isReadOnly={isReadOnly}
					errorMessage={
						askUserQuestionErrorId === interrupt.tool_call_id
							? askUserQuestionError
							: ""
					}
					onSubmit={onSubmitAskUserQuestion}
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

const BRANCH_IMPORT_HIGHLIGHT_MS = 2400;

/** Scrolls to and briefly highlights an import the merge review asked for. */
function useBranchImportHighlight(transcriptItems: TranscriptItem[]) {
	const [highlightedId, setHighlightedId] = useState<string | null>(null);

	useEffect(() => {
		const match = [...transcriptItems]
			.reverse()
			.find(
				(item): item is TranscriptDisplayMessage =>
					item.kind === "message" &&
					Boolean(item.branchImport) &&
					matchPendingBranchImportHighlight(
						item.branchImport as NonNullable<typeof item.branchImport>,
					),
			);
		if (!match) return;
		clearPendingBranchImportHighlight();
		setHighlightedId(match.id);
		const frame = window.requestAnimationFrame(() => {
			const element = document.getElementById(branchImportCardDomId(match.id));
			const reduceMotion = window.matchMedia(
				"(prefers-reduced-motion: reduce)",
			).matches;
			element?.scrollIntoView({
				behavior: reduceMotion ? "auto" : "smooth",
				block: "center",
			});
			element?.focus({ preventScroll: true });
		});
		return () => window.cancelAnimationFrame(frame);
	}, [transcriptItems]);

	useEffect(() => {
		if (!highlightedId) return;
		const timer = window.setTimeout(
			() => setHighlightedId(null),
			BRANCH_IMPORT_HIGHLIGHT_MS,
		);
		return () => window.clearTimeout(timer);
	}, [highlightedId]);

	return highlightedId;
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
		if (
			itemContent === handoffMessage ||
			(action.delivery === "after_answer" &&
				itemContent.endsWith(handoffMessage))
		) {
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
	return item.kind === "message" && normalizeMessageType(item.type) === "human";
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
