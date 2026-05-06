import type {
	FocusAgentBranchActionProposal,
	FocusAgentToolApprovalInterrupt,
	FocusAgentToolCallEvent,
	FocusAgentToolEvent,
	TurnFailedPayload,
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
	normalizeText,
	shouldHideStreamingInternalContent,
} from "./message-transcript";

interface MessageListProps {
	isReadOnly?: boolean;
	isStreaming?: boolean;
	messages: Array<Record<string, unknown>>;
	assistantMessage?: string | null;
	streamVisibleText?: string;
	streamReasoningText?: string;
	streamToolCalls?: FocusAgentToolCallEvent[];
	streamToolEvents?: FocusAgentToolEvent[];
	streamFailed?: TurnFailedPayload;
	branchActions?: FocusAgentBranchActionProposal[];
	branchActionErrors?: Record<string, string>;
	branchActionInFlightId?: string | null;
	toolApprovalInterrupts?: FocusAgentToolApprovalInterrupt[];
	toolApprovalError?: string;
	toolApprovalErrorId?: string | null;
	toolApprovalInFlightId?: string | null;
	isChineseUi?: boolean;
	onEditMessage?: (message: { id: string; content: string }) => void;
	onExecuteBranchAction?: (action: FocusAgentBranchActionProposal) => void;
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
	streamToolCalls,
	streamToolEvents,
	streamFailed,
	branchActions = [],
	branchActionErrors = {},
	branchActionInFlightId = null,
	toolApprovalInterrupts = [],
	toolApprovalError = "",
	toolApprovalErrorId = null,
	toolApprovalInFlightId = null,
	isChineseUi = false,
	onEditMessage,
	onExecuteBranchAction,
	onDismissBranchAction,
	onDecideToolApproval,
}: MessageListProps) {
	const transcriptItems = useMemo(
		() => buildTranscriptItems(messages, assistantMessage),
		[assistantMessage, messages],
	);
	const visibleStreamReply = shouldHideStreamingInternalContent(
		streamVisibleText,
	)
		? ""
		: normalizeText(streamVisibleText)
			? String(streamVisibleText)
			: "";

	return (
		<div className="fa-message-list">
			{transcriptItems.map((item) => {
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

			{branchActions.map((action) => (
				<BranchActionCard
					key={action.action_id}
					action={action}
					isChineseUi={isChineseUi}
					isReadOnly={isReadOnly}
					errorMessage={branchActionErrors[action.action_id]}
					isBusy={branchActionInFlightId === action.action_id}
					onExecute={onExecuteBranchAction}
					onDismiss={onDismissBranchAction}
				/>
			))}

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
				reasoningText={streamReasoningText}
				toolCalls={streamToolCalls}
				toolEvents={streamToolEvents}
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
