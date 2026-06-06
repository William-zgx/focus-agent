import type { FocusAgentModelOption } from "@focus-agent/web-sdk";
import type { Dispatch, SetStateAction } from "react";

import { thinkingModeRequestValueForModel } from "./message-composer-helpers";
import type { SendMessageResult } from "./stream-entry-state";

type SendMessage = (
	message: string,
	overrides?: {
		model?: string;
		thinkingMode?: string;
	},
) => Promise<SendMessageResult>;

type SetComposerMessage = Dispatch<SetStateAction<string>>;

export function composerSendOverrides({
	activeModel,
	activeThinkingMode,
	modelId,
}: {
	activeModel?: FocusAgentModelOption;
	activeThinkingMode: string;
	modelId: string;
}) {
	return {
		model: modelId || undefined,
		...(activeModel?.supports_thinking
			? {
					thinkingMode: thinkingModeRequestValueForModel(
						activeModel,
						activeThinkingMode,
					),
				}
			: {}),
	};
}

export async function submitComposerMessage({
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
}: {
	activeModel?: FocusAgentModelOption;
	activeThinkingMode: string;
	editDraft?: { id: string; content: string } | null;
	isReadOnly: boolean;
	isStreaming: boolean;
	message: string;
	modelId: string;
	onClearEditDraft?: () => void;
	onSendMessage: SendMessage;
	resetEditDraftSignature: () => void;
	setMessage: SetComposerMessage;
}) {
	const trimmed = message.trim();
	if (!trimmed || isStreaming || isReadOnly) return;
	const restoreSubmittedDraft = () => {
		setMessage((current) => (current.trim() ? current : message));
	};
	const wasEditing = Boolean(editDraft);
	if (wasEditing) {
		resetEditDraftSignature();
		onClearEditDraft?.();
	}
	setMessage("");
	let result: SendMessageResult;
	try {
		result = await onSendMessage(
			trimmed,
			composerSendOverrides({
				activeModel,
				activeThinkingMode,
				modelId,
			}),
		);
	} catch (error) {
		restoreSubmittedDraft();
		throw error;
	}
	if (!result.ok && !result.aborted) {
		restoreSubmittedDraft();
	}
}
