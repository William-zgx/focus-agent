import type { ContextUsageResponse } from "@focus-agent/web-sdk";
import { useEffect, useState } from "react";

interface UseThreadPageDraftStateOptions {
	contextUsage?: ContextUsageResponse | null;
	isMergedReadOnlyThread: boolean;
	threadId: string;
}

export function useThreadPageDraftState({
	contextUsage,
	isMergedReadOnlyThread,
	threadId,
}: UseThreadPageDraftStateOptions) {
	const [editDraft, setEditDraft] = useState<{
		id: string;
		content: string;
	} | null>(null);
	const [previewContextUsage, setPreviewContextUsage] =
		useState<ContextUsageResponse | null>(null);

	useEffect(() => {
		resetThreadDraftState(threadId, setEditDraft, setPreviewContextUsage);
	}, [threadId]);

	useEffect(() => {
		resetPreviewContextUsage(threadId, contextUsage, setPreviewContextUsage);
	}, [contextUsage, threadId]);

	useEffect(() => {
		if (isMergedReadOnlyThread) {
			setEditDraft(null);
		}
	}, [isMergedReadOnlyThread]);

	return {
		editDraft,
		previewContextUsage,
		setEditDraft,
		setPreviewContextUsage,
	};
}

function resetThreadDraftState(
	threadId: string,
	setEditDraft: (value: { id: string; content: string } | null) => void,
	setPreviewContextUsage: (value: ContextUsageResponse | null) => void,
) {
	void threadId;
	setEditDraft(null);
	setPreviewContextUsage(null);
}

function resetPreviewContextUsage(
	threadId: string,
	contextUsage: ContextUsageResponse | null | undefined,
	setPreviewContextUsage: (value: ContextUsageResponse | null) => void,
) {
	void threadId;
	void contextUsage;
	setPreviewContextUsage(null);
}
