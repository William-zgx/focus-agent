import {
	createInitialStreamState,
	type FocusAgentStreamState,
} from "@focus-agent/web-sdk";

export interface SendMessageOverrides {
	model?: string;
	thinkingMode?: string;
}

export interface PendingUserMessage {
	id: string;
	content: string;
	threadId: string;
}

export interface ThreadStreamEntry {
	streamState: FocusAgentStreamState | null;
	pendingUserMessage: PendingUserMessage | null;
	isStreaming: boolean;
}

export interface SendMessageResult {
	ok: boolean;
	aborted?: boolean;
}

export function resolveThinkingModeForRequest(
	overrides: SendMessageOverrides | undefined,
	selectedThinkingMode: string | undefined,
) {
	if (overrides && Object.hasOwn(overrides, "thinkingMode")) {
		return overrides.thinkingMode;
	}
	return selectedThinkingMode || undefined;
}

export function createThreadStreamEntry(
	overrides?: Partial<ThreadStreamEntry>,
): ThreadStreamEntry {
	return {
		streamState: null,
		pendingUserMessage: null,
		isStreaming: false,
		...(overrides ?? {}),
	};
}

export function createOptimisticThreadStreamEntry(
	threadId: string,
	message: string,
): ThreadStreamEntry {
	return createThreadStreamEntry({
		pendingUserMessage: {
			id: `optimistic-user-${Date.now()}`,
			content: message,
			threadId,
		},
		streamState: createInitialStreamState(),
		isStreaming: true,
	});
}

export function nextThreadEntryMap(
	current: Record<string, ThreadStreamEntry>,
	threadId: string,
	value: ThreadStreamEntry | null,
): Record<string, ThreadStreamEntry> {
	if (!threadId) {
		return current;
	}
	if (value === null) {
		if (!Object.hasOwn(current, threadId)) {
			return current;
		}
		const next = { ...current };
		delete next[threadId];
		return next;
	}
	return {
		...current,
		[threadId]: value,
	};
}

export function patchThreadEntry(
	current: Record<string, ThreadStreamEntry>,
	threadId: string,
	patch: Partial<ThreadStreamEntry>,
): Record<string, ThreadStreamEntry> {
	const nextEntry = {
		...(current[threadId] ?? createThreadStreamEntry()),
		...patch,
	};
	if (
		nextEntry.streamState === null &&
		nextEntry.pendingUserMessage === null &&
		!nextEntry.isStreaming
	) {
		return nextThreadEntryMap(current, threadId, null);
	}
	return nextThreadEntryMap(current, threadId, nextEntry);
}
