import { useSyncExternalStore } from "react";

/**
 * Hands the fork dialog's goal to the thread page so it can be sent as the new
 * branch's first message once the page has navigated to the child thread.
 */
type PendingBranchGoal = { threadId: string; message: string };

let pendingGoal: PendingBranchGoal | null = null;
const listeners = new Set<() => void>();

function emit() {
	for (const listener of listeners) listener();
}

export function setPendingBranchGoal(threadId: string, message: string) {
	const trimmed = message.trim();
	pendingGoal = threadId && trimmed ? { threadId, message: trimmed } : null;
	emit();
}

export function takePendingBranchGoal(threadId: string) {
	if (!pendingGoal || pendingGoal.threadId !== threadId) return null;
	const { message } = pendingGoal;
	pendingGoal = null;
	emit();
	return message;
}

function subscribe(listener: () => void) {
	listeners.add(listener);
	return () => {
		listeners.delete(listener);
	};
}

export function usePendingBranchGoalThreadId() {
	return useSyncExternalStore(
		subscribe,
		() => pendingGoal?.threadId ?? "",
		() => "",
	);
}
