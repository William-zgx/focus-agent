import { createInitialStreamState } from "@focus-agent/web-sdk";

import type { ThreadStreamEntry } from "./stream-entry-state";

interface StreamRequestCleanup {
	clearActiveThread: boolean;
	clearPendingUserMessage: boolean;
	clearStreamState: boolean;
}

export function resolveStreamRequestCleanup(
	sendSucceeded: boolean,
	aborted: boolean,
): StreamRequestCleanup {
	if (sendSucceeded) {
		return {
			clearActiveThread: true,
			clearPendingUserMessage: true,
			clearStreamState: true,
		};
	}
	if (aborted) {
		return {
			clearActiveThread: true,
			clearPendingUserMessage: true,
			clearStreamState: true,
		};
	}
	return {
		clearActiveThread: false,
		clearPendingUserMessage: true,
		clearStreamState: false,
	};
}

export function isAbortError(error: unknown, controller: AbortController) {
	return (
		controller.signal.aborted ||
		(error instanceof Error && error.name === "AbortError")
	);
}

export function messageFromStreamError(error: unknown) {
	return error instanceof Error ? error.message : "Failed to send message.";
}

export function createFailedStreamEntryPatch(
	error: unknown,
): Partial<ThreadStreamEntry> {
	return {
		streamState: {
			...createInitialStreamState(),
			failed: {
				error: "request_failed",
				message: messageFromStreamError(error),
			},
			isClosed: true,
		},
	};
}
