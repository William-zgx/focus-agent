import type { FocusAgentModelOption } from "@focus-agent/web-sdk";

import { thinkingModeRequestValueForModel } from "./message-composer-helpers";

type SendMessage = (
  message: string,
  overrides?: {
    model?: string;
    thinkingMode?: string;
  },
) => Promise<{ ok: boolean }>;

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
          thinkingMode: thinkingModeRequestValueForModel(activeModel, activeThinkingMode),
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
  setMessage: (message: string) => void;
}) {
  const trimmed = message.trim();
  if (!trimmed || isStreaming || isReadOnly) return;
  const wasEditing = Boolean(editDraft);
  if (wasEditing) {
    resetEditDraftSignature();
    onClearEditDraft?.();
  }
  const result = await onSendMessage(
    trimmed,
    composerSendOverrides({
      activeModel,
      activeThinkingMode,
      modelId,
    }),
  );
  if (result.ok) {
    setMessage("");
  }
}
