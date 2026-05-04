import type {
	ContextUsageResponse,
	FocusAgentBranchActionProposal,
	FocusAgentStreamState,
} from "@focus-agent/web-sdk";
import type { RefObject } from "react";

import { MessageList } from "@/entities/messages/message-list";
import { MessageComposer } from "@/features/thread-stream/message-composer";

interface ThreadPageContentProps {
	assistantMessage?: string | null;
	branchActionErrors: Record<string, string>;
	branchActionInFlightId: string | null;
	branchActions: FocusAgentBranchActionProposal[];
	compactContextError?: string;
	contextUsage?: ContextUsageResponse | null;
	editDraft: { id: string; content: string } | null;
	hasTranscriptContent: boolean;
	historyRef: RefObject<HTMLDivElement | null>;
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
	streamState: FocusAgentStreamState | null;
	threadContextUsage?: ContextUsageResponse | null;
	threadError?: unknown;
}

export function ThreadPageContent({
	assistantMessage,
	branchActionErrors,
	branchActionInFlightId,
	branchActions,
	compactContextError = "",
	contextUsage,
	editDraft,
	hasTranscriptContent,
	historyRef,
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
	onEditMessage,
	onExecuteBranchAction,
	onPreviewContextUsage,
	onSendMessage,
	onStopStreaming,
	previewContextError = "",
	previewContextUsage,
	selectedModel,
	selectedThinkingMode,
	streamState,
	threadContextUsage,
	threadError,
}: ThreadPageContentProps) {
	const composerContextUsage =
		previewContextUsage ?? contextUsage ?? threadContextUsage ?? null;
	const contextUsageError = previewContextError || compactContextError;

	return (
		<div className="fa-thread-layout">
			<div className="fa-transcript-panel">
				<section className="fa-chat-transcript">
					<div className="fa-chat-history" ref={historyRef}>
						<div
							className={`fa-chat-history-content ${hasTranscriptContent ? "is-populated" : ""}`.trim()}
						>
							{isLoading ? (
								<div className="fa-inline-notice">
									{isChineseUi
										? "正在加载线程状态..."
										: "Loading thread state..."}
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
								<MessageList
									assistantMessage={assistantMessage}
									isReadOnly={isMergedReadOnlyThread}
									isStreaming={isStreaming}
									messages={messages}
									branchActions={branchActions}
									branchActionErrors={branchActionErrors}
									branchActionInFlightId={branchActionInFlightId}
									isChineseUi={isChineseUi}
									onEditMessage={onEditMessage}
									onExecuteBranchAction={onExecuteBranchAction}
									onDismissBranchAction={onDismissBranchAction}
									streamFailed={streamState?.failed}
									streamToolCalls={streamState?.toolCalls}
									streamToolEvents={streamState?.toolEvents}
									streamVisibleText={streamState?.visibleText}
									streamReasoningText={streamState?.reasoningText}
								/>
							) : (
								<div className="fa-chat-empty">
									{isChineseUi
										? "从这里开始聊天。只要 Agent 产生分支，左侧就会显示出来。"
										: "Start chatting here. Branches appear on the left whenever the agent forks work."}
								</div>
							)}
						</div>
					</div>
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
