import type {
	ContextUsageResponse,
	FocusAgentBranchActionProposal,
	FocusAgentBranchDecisionSummary,
	FocusAgentStreamState,
	FocusAgentToolApprovalInterrupt,
} from "@focus-agent/web-sdk";
import type { StickToBottomInstance } from "use-stick-to-bottom";

import { MessageList } from "@/entities/messages/message-list";
import { BranchDecisionSummaryPanel } from "@/features/branch-decisions/branch-decision-summary-panel";
import { MessageComposer } from "@/features/thread-stream/message-composer";
import { EmptyState, Skeleton } from "@/shared/ui/primitives";

import { ConversationViewport } from "./conversation-viewport";

interface ThreadPageContentProps {
	assistantMessage?: string | null;
	branchActionErrors: Record<string, string>;
	branchActionInFlightId: string | null;
	branchActions: FocusAgentBranchActionProposal[];
	branchDecisionSummary?: FocusAgentBranchDecisionSummary | null;
	compactContextError?: string;
	contextUsage?: ContextUsageResponse | null;
	editDraft: { id: string; content: string } | null;
	hasTranscriptContent: boolean;
	isChineseUi: boolean;
	isCompactingContext: boolean;
	isContextUsageLoading: boolean;
	isLoading: boolean;
	isMergedReadOnlyThread: boolean;
	isStreaming: boolean;
	messages: Array<Record<string, unknown>>;
	onClearEditDraft: () => void;
	onCompactContext: () => Promise<void> | void;
	onDismissBranchAction: (action: FocusAgentBranchActionProposal) => void;
	onDecideToolApproval: (
		interrupt: FocusAgentToolApprovalInterrupt,
		approved: boolean,
	) => void;
	onEditMessage: (message: { id: string; content: string }) => void;
	onExecuteBranchAction: (action: FocusAgentBranchActionProposal) => void;
	onPreviewContextUsage: (draftMessage: string) => void;
	onSendMessage: (
		message: string,
		overrides?: {
			model?: string;
			thinkingMode?: string;
		},
	) => Promise<{ ok: boolean }>;
	onStopStreaming: () => void;
	previewContextError?: string;
	previewContextUsage?: ContextUsageResponse | null;
	selectedModel?: string;
	selectedThinkingMode?: string;
	stickToBottom: StickToBottomInstance;
	streamState: FocusAgentStreamState | null;
	threadContextUsage?: ContextUsageResponse | null;
	threadError?: unknown;
	threadId: string;
	rootThreadId?: string;
	toolApprovalError?: string;
	toolApprovalErrorId?: string | null;
	toolApprovalInFlightId?: string | null;
	toolApprovalInterrupts: FocusAgentToolApprovalInterrupt[];
}

export function ThreadPageContent({
	assistantMessage,
	branchActionErrors,
	branchActionInFlightId,
	branchActions,
	branchDecisionSummary,
	compactContextError = "",
	contextUsage,
	editDraft,
	hasTranscriptContent,
	isChineseUi,
	isCompactingContext,
	isContextUsageLoading,
	isLoading,
	isMergedReadOnlyThread,
	isStreaming,
	messages,
	onClearEditDraft,
	onCompactContext,
	onDismissBranchAction,
	onDecideToolApproval,
	onEditMessage,
	onExecuteBranchAction,
	onPreviewContextUsage,
	onSendMessage,
	onStopStreaming,
	previewContextError = "",
	previewContextUsage,
	selectedModel,
	selectedThinkingMode,
	stickToBottom,
	streamState,
	threadContextUsage,
	threadError,
	threadId,
	rootThreadId,
	toolApprovalError = "",
	toolApprovalErrorId = null,
	toolApprovalInFlightId = null,
	toolApprovalInterrupts,
}: ThreadPageContentProps) {
	const composerContextUsage =
		previewContextUsage ?? contextUsage ?? threadContextUsage ?? null;
	const contextUsageError = previewContextError || compactContextError;
	const messageListProps = {
		assistantMessage,
		isReadOnly: isMergedReadOnlyThread,
		isStreaming,
		messages,
		branchActions,
		branchActionErrors,
		branchActionInFlightId,
		toolApprovalInterrupts,
		toolApprovalError,
		toolApprovalErrorId,
		toolApprovalInFlightId,
		isChineseUi,
		onEditMessage,
		onExecuteBranchAction,
		onDismissBranchAction,
		onDecideToolApproval,
		streamFailed: streamState?.failed,
		streamVisibleText: streamState?.visibleText,
		streamReasoningText: streamState?.reasoningText,
		streamProcessingSteps: streamState?.processingSteps,
	};

	return (
		<div className="fa-thread-layout">
			<div className="fa-transcript-panel">
				<section className="fa-chat-transcript">
					<BranchDecisionSummaryPanel
						isChineseUi={isChineseUi}
						isReadOnly={isMergedReadOnlyThread}
						rootThreadId={rootThreadId}
						summary={branchDecisionSummary}
						threadId={threadId}
					/>
					<ConversationViewport
						hasTranscriptContent={hasTranscriptContent}
						isChineseUi={isChineseUi}
						stickToBottom={stickToBottom}
					>
						{isLoading ? (
							<div className="fa-inline-notice">
								<Skeleton lines={2} />
							</div>
						) : null}
						{threadError ? (
							<div className="fa-inline-notice is-danger">
								{isChineseUi
									? "加载线程状态失败。"
									: "Failed to load thread state."}
							</div>
						) : null}
						{hasTranscriptContent ? (
							<MessageList {...messageListProps} />
						) : (
							<EmptyState
								className="fa-chat-empty"
								title={
									isChineseUi
										? "从这里开始聊天。只要 Agent 产生分支，左侧就会显示出来。"
										: "Start chatting here. Branches appear on the left whenever the agent forks work."
								}
							/>
						)}
					</ConversationViewport>
				</section>

				<section className="fa-composer-slot">
					<MessageComposer
						editDraft={editDraft}
						isReadOnly={isMergedReadOnlyThread}
						isStreaming={isStreaming}
						onClearEditDraft={onClearEditDraft}
						onSendMessage={onSendMessage}
						onStopStreaming={onStopStreaming}
						contextUsage={composerContextUsage}
						contextUsageError={contextUsageError}
						isContextUsageLoading={isContextUsageLoading}
						isCompactingContext={isCompactingContext}
						onCompactContext={onCompactContext}
						onPreviewContextUsage={onPreviewContextUsage}
						selectedModel={selectedModel}
						selectedThinkingMode={selectedThinkingMode}
					/>
				</section>
			</div>
		</div>
	);
}
