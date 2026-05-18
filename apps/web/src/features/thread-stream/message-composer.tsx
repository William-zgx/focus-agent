import type {
	ContextUsageResponse,
	FocusAgentModelOption,
} from "@focus-agent/web-sdk";
import {
	type FormEvent,
	type KeyboardEvent,
	useEffect,
	useId,
	useState,
} from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useModels } from "@/features/models/use-models";
import { Button, IconButton } from "@/shared/ui/primitives";
import { tooltipProps } from "@/shared/ui/tooltip";
import { ContextUsageMeter } from "./message-composer-components";
import { useMessageComposerDraft } from "./message-composer-draft";
import {
	effectiveThinkingModeForModel,
	mergedBranchReadOnlyLabel,
	nextThinkingModeForModelSelection,
	normalizeThinkingMode,
} from "./message-composer-helpers";
import { MessageComposerModelSelector } from "./message-composer-model-selector";
import { submitComposerMessage } from "./message-composer-submit";

export {
	contextUsagePercent,
	contextUsageRemainingPercent,
	contextUsageTone,
	effectiveThinkingModeForModel,
	formatContextMarkerCount,
	nextThinkingModeForModelSelection,
	shouldShowContextCompactAction,
	thinkingModeRequestValueForModel,
} from "./message-composer-helpers";

interface MessageComposerProps {
	isReadOnly?: boolean;
	isStreaming: boolean;
	onSendMessage: (
		message: string,
		overrides?: {
			model?: string;
			thinkingMode?: string;
		},
	) => Promise<{ ok: boolean }>;
	onStopStreaming: () => void;
	selectedModel?: string;
	selectedThinkingMode?: string;
	editDraft?: { id: string; content: string } | null;
	onClearEditDraft?: () => void;
	contextUsage?: ContextUsageResponse | null;
	contextUsageError?: string;
	isContextUsageLoading?: boolean;
	isCompactingContext?: boolean;
	onCompactContext?: () => Promise<void> | void;
	onPreviewContextUsage?: (draftMessage: string) => void;
}

export function MessageComposer({
	isReadOnly = false,
	isStreaming,
	onSendMessage,
	onStopStreaming,
	selectedModel,
	selectedThinkingMode,
	editDraft,
	onClearEditDraft,
	contextUsage,
	contextUsageError = "",
	isContextUsageLoading = false,
	isCompactingContext = false,
	onCompactContext,
	onPreviewContextUsage,
}: MessageComposerProps) {
	const { data } = useModels();
	const { isChineseUi } = useShellUi();
	const [modelId, setModelId] = useState(selectedModel ?? "");
	const [thinkingMode, setThinkingMode] = useState(selectedThinkingMode ?? "");
	const [modelPanelOpen, setModelPanelOpen] = useState(false);
	const textareaId = useId();
	const { message, resetEditDraftSignature, setMessage, textareaRef } =
		useMessageComposerDraft({
			editDraft,
			isReadOnly,
			onEditDraftLoaded: () => setModelPanelOpen(false),
			onPreviewContextUsage,
		});

	const allModels = data?.models ?? [];
	const activeModel =
		allModels.find((item: FocusAgentModelOption) => item.id === modelId) ??
		allModels[0];
	const activeThinkingMode = effectiveThinkingModeForModel(
		activeModel,
		thinkingMode,
	);
	const readOnlyReason = mergedBranchReadOnlyLabel(isChineseUi);

	useEffect(() => {
		setModelId(selectedModel ?? "");
	}, [selectedModel]);

	useEffect(() => {
		setThinkingMode(normalizeThinkingMode(selectedThinkingMode));
	}, [selectedThinkingMode]);

	useEffect(() => {
		setThinkingMode((current) =>
			effectiveThinkingModeForModel(activeModel, current),
		);
	}, [activeModel]);

	async function submitMessage() {
		await submitComposerMessage({
			activeModel,
			activeThinkingMode,
			editDraft,
			isReadOnly,
			isStreaming,
			message,
			modelId,
			onClearEditDraft,
			onSendMessage,
			resetEditDraftSignature,
			setMessage,
		});
	}

	async function handleSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		await submitMessage();
	}

	function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
		if (
			event.key !== "Enter" ||
			event.shiftKey ||
			event.nativeEvent.isComposing
		) {
			return;
		}
		event.preventDefault();
		void submitMessage();
	}

	function selectModel(nextModelId: string) {
		const nextModel = allModels.find(
			(item: FocusAgentModelOption) => item.id === nextModelId,
		);
		setModelId(nextModelId);
		setThinkingMode((current) =>
			nextThinkingModeForModelSelection(
				nextModel,
				nextModelId,
				modelId,
				current,
			),
		);
		setModelPanelOpen(false);
	}

	function toggleModelThinkingMode(
		nextModelId: string,
		currentThinkingMode: string,
	) {
		setModelId(nextModelId);
		setThinkingMode(currentThinkingMode === "enabled" ? "disabled" : "enabled");
		setModelPanelOpen(false);
	}

	return (
		<form className="fa-composer-card fa-composer" onSubmit={handleSubmit}>
			{editDraft ? (
				<div className="fa-composer-edit-banner">
					<div className="fa-composer-edit-copy">
						<div className="fa-composer-edit-title">
							{isChineseUi
								? "正在编辑上一条用户消息"
								: "Editing previous user prompt"}
						</div>
						<div className="fa-composer-edit-note">
							{isChineseUi
								? "重新发送后会以新的消息继续当前线程。"
								: "Sending again will continue this thread with a revised prompt."}
						</div>
					</div>
					<Button
						className="fa-composer-edit-cancel"
						onClick={onClearEditDraft}
						type="button"
						variant="ghost"
						size="sm"
					>
						{isChineseUi ? "取消" : "Cancel"}
					</Button>
				</div>
			) : null}

			<div
				className={`fa-composer-shell fa-composer-input-shell ${isStreaming ? "is-streaming" : ""} ${
					isReadOnly ? "is-readonly" : ""
				}`}
			>
				<label className="sr-only" htmlFor={textareaId}>
					{isReadOnly
						? `${isChineseUi ? "消息" : "Message"} - ${readOnlyReason}`
						: isChineseUi
							? "消息"
							: "Message"}
				</label>
				<div className="fa-composer-textarea-row fa-composer-input-row">
					<textarea
						id={textareaId}
						className="fa-composer-textarea"
						placeholder={
							isReadOnly
								? isChineseUi
									? "这个分支已经合并，不能继续发送消息。"
									: "This branch has already been merged. You can no longer send messages here."
								: isChineseUi
									? "先在主线程里展开对话，只有在需要单独探索一个方向时再创建分支。"
									: "Start on the main thread, then branch only when you want to explore a separate direction."
						}
						aria-label={
							isReadOnly
								? `${isChineseUi ? "消息" : "Message"} - ${readOnlyReason}`
								: isChineseUi
									? "消息"
									: "Message"
						}
						readOnly={isReadOnly}
						ref={textareaRef}
						title={isReadOnly ? readOnlyReason : undefined}
						value={message}
						onChange={(event) => setMessage(event.target.value)}
						onKeyDown={handleComposerKeyDown}
					/>
				</div>

				<div className="fa-composer-footer-row">
					<div className="fa-composer-model-row">
						<div className="fa-composer-model-controls">
							<MessageComposerModelSelector
								activeModel={activeModel}
								activeThinkingMode={activeThinkingMode}
								allModels={allModels}
								isChineseUi={isChineseUi}
								isStreaming={isStreaming}
								modelId={modelId}
								modelPanelOpen={modelPanelOpen}
								onModelPanelOpenChange={setModelPanelOpen}
								onSelectModel={selectModel}
								onToggleModelThinkingMode={toggleModelThinkingMode}
								thinkingMode={thinkingMode}
							/>
						</div>
					</div>

					<div className="fa-composer-actions-row">
						<ContextUsageMeter
							usage={contextUsage}
							error={contextUsageError}
							isChineseUi={isChineseUi}
							isLoading={isContextUsageLoading}
							isCompacting={isCompactingContext}
							isDisabled={isStreaming || isReadOnly}
							onCompact={onCompactContext}
						/>
						<div className="fa-composer-inline-actions">
							<IconButton
								className="fa-composer-icon-button is-clear"
								label={isChineseUi ? "清空输入" : "Clear input"}
								{...tooltipProps(isChineseUi ? "清空输入" : "Clear input")}
								disabled={isStreaming || !message}
								onClick={() => setMessage("")}
								type="button"
							>
								<span className="fa-composer-icon" aria-hidden="true">
									<svg viewBox="0 0 20 20" aria-hidden="true">
										<path
											d="M7.65 3.25c-.83 0-1.5.67-1.5 1.5v.4H4.5a.85.85 0 0 0 0 1.7h.58l.63 8.02a2.05 2.05 0 0 0 2.05 1.88h4.48a2.05 2.05 0 0 0 2.05-1.88l.63-8.02h.58a.85.85 0 1 0 0-1.7h-1.65v-.4c0-.83-.67-1.5-1.5-1.5h-4.7Z"
											fill="currentColor"
											opacity="0.9"
										/>
										<path
											d="M8.5 9.1v4.2M11.5 9.1v4.2"
											stroke="currentColor"
											strokeWidth="1.5"
											strokeLinecap="round"
										/>
									</svg>
								</span>
								<span className="sr-only">
									{isChineseUi ? "清空输入" : "Clear input"}
								</span>
							</IconButton>

							{isStreaming ? (
								<IconButton
									className="fa-composer-icon-button is-stop"
									label={isChineseUi ? "停止生成" : "Stop generation"}
									{...tooltipProps(
										isChineseUi ? "停止生成" : "Stop generation",
									)}
									type="button"
									onClick={onStopStreaming}
								>
									<span className="fa-composer-icon" aria-hidden="true">
										<svg viewBox="0 0 20 20" aria-hidden="true">
											<rect
												x="5.2"
												y="5.2"
												width="9.6"
												height="9.6"
												rx="2.2"
												fill="currentColor"
											/>
										</svg>
									</span>
									<span className="sr-only">
										{isChineseUi ? "停止生成" : "Stop generation"}
									</span>
								</IconButton>
							) : (
								<IconButton
									className="fa-composer-icon-button is-send"
									label={
										isReadOnly
											? readOnlyReason
											: isChineseUi
												? "发送消息"
												: "Send message"
									}
									{...tooltipProps(
										isReadOnly
											? readOnlyReason
											: isChineseUi
												? "发送消息"
												: "Send message",
									)}
									disabled={isStreaming || isReadOnly || !message.trim()}
									type="submit"
								>
									<span className="fa-composer-icon" aria-hidden="true">
										<svg viewBox="0 0 20 20" aria-hidden="true">
											<path
												d="M16.99 3.01a.9.9 0 0 0-.94-.16L3.58 8.38a.9.9 0 0 0 .07 1.68l5 1.88 1.88 5a.9.9 0 0 0 1.68.07l5.53-12.47a.9.9 0 0 0-.75-1.53Z"
												fill="currentColor"
											/>
											<path
												d="m8.14 10.12 4.25-4.25"
												stroke="rgba(255,255,255,0.92)"
												strokeWidth="1.4"
												strokeLinecap="round"
											/>
										</svg>
									</span>
									<span className="sr-only">
										{isChineseUi ? "发送消息" : "Send message"}
									</span>
								</IconButton>
							)}
						</div>
					</div>
				</div>

					<span className="sr-only">
						{isChineseUi
							? "这里先保持当前线程聚焦。只有当你想把问题拆到独立方向时，再创建分支。"
							: "Keep the current thread focused here. Create a branch only when you want to split into a separate direction."}
					</span>
				</div>
			</form>
	);
}
