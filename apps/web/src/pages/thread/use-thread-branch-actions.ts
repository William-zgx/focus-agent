import {
	FocusAgentRequestError,
	type FocusAgentBranchActionExecuteResponse,
	type FocusAgentBranchActionNavigation,
	type FocusAgentBranchActionProposal,
} from "@focus-agent/web-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

function navigationFromBranchActionResult(
	result: FocusAgentBranchActionExecuteResponse,
): FocusAgentBranchActionNavigation | null {
	if (result.navigation) {
		return result.navigation;
	}
	if (result.branch_action.navigation) {
		return result.branch_action.navigation;
	}
	if (result.branch_record) {
		return {
			root_thread_id: result.branch_record.root_thread_id,
			thread_id: result.branch_record.child_thread_id,
		};
	}
	return null;
}

function branchActionHandoffMessage(
	result: FocusAgentBranchActionExecuteResponse,
): string {
	return String(result.branch_action.handoff_message ?? "").trim();
}

function branchActionProposalHandoffMessage(
	action: FocusAgentBranchActionProposal,
): string {
	return String(action.handoff_message ?? "").trim();
}

interface BranchActionHandoffRun {
	threadId: string;
	message: string;
}

interface UseThreadBranchActionsOptions {
	onContinueCurrentBranch?: (input: BranchActionHandoffRun) => Promise<unknown>;
	onRunHandoff?: (input: BranchActionHandoffRun) => Promise<unknown>;
}

const THREAD_BUSY_RETRY_ATTEMPTS = 80;
const THREAD_BUSY_RETRY_DELAY_MS = 500;

class ThreadBranchActionRetryCancelled extends Error {
	constructor() {
		super("Branch action request was cancelled.");
		this.name = "ThreadBranchActionRetryCancelled";
	}
}

function isThreadBusyConflict(error: unknown): boolean {
	if (!(error instanceof FocusAgentRequestError) || error.status !== 409) {
		return false;
	}
	const text = [error.message, JSON.stringify(error.data ?? {})]
		.join(" ")
		.toLowerCase();
	return text.includes("still processing") || text.includes("previous turn");
}

function delay(ms: number) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

async function retryThreadBusyConflict<T>(
	operation: () => Promise<T>,
	shouldContinue: () => boolean,
): Promise<T> {
	let lastError: unknown;
	for (let attempt = 0; attempt < THREAD_BUSY_RETRY_ATTEMPTS; attempt += 1) {
		if (!shouldContinue()) {
			throw new ThreadBranchActionRetryCancelled();
		}
		try {
			const result = await operation();
			if (!shouldContinue()) {
				throw new ThreadBranchActionRetryCancelled();
			}
			return result;
		} catch (error) {
			lastError = error;
			if (error instanceof ThreadBranchActionRetryCancelled) {
				throw error;
			}
			if (!isThreadBusyConflict(error)) {
				throw error;
			}
			await delay(THREAD_BUSY_RETRY_DELAY_MS);
		}
	}
	throw lastError;
}

export function useThreadBranchActions(
	threadId: string,
	options: UseThreadBranchActionsOptions = {},
) {
	const { client } = useFocusAgent();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { isChineseUi } = useShellUi();
	const [branchActionInFlightId, setBranchActionInFlightId] = useState<
		string | null
	>(null);
	const [branchActionErrors, setBranchActionErrors] = useState<
		Record<string, string>
	>({});
	const branchActionInFlightRef = useRef<string | null>(null);
	const branchActionRequestEpochRef = useRef(0);
	const branchActionThreadIdRef = useRef(threadId);

	const refreshBranchActionSurfaces = useCallback(
		async (currentThreadId: string) => {
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
				queryClient.invalidateQueries({
					queryKey: queryKeys.branchTrees,
				}),
				queryClient.invalidateQueries({
					queryKey: queryKeys.thread(currentThreadId),
				}),
			]);
		},
		[queryClient],
	);

	const beginBranchActionRequest = useCallback((actionId: string) => {
		if (branchActionInFlightRef.current) {
			return null;
		}
		branchActionRequestEpochRef.current += 1;
		branchActionInFlightRef.current = actionId;
		setBranchActionInFlightId(actionId);
		setBranchActionErrors((current) => {
			const next = { ...current };
			delete next[actionId];
			return next;
		});
		return branchActionRequestEpochRef.current;
	}, []);

	const endBranchActionRequest = useCallback((actionId: string) => {
		if (branchActionInFlightRef.current === actionId) {
			branchActionInFlightRef.current = null;
			setBranchActionInFlightId(null);
		}
	}, []);

	const isCurrentBranchActionRequest = useCallback(
		(requestEpoch: number, sourceThreadId: string) =>
			branchActionRequestEpochRef.current === requestEpoch &&
			threadId === sourceThreadId,
		[threadId],
	);

	const refreshThreadAfterBranchActionFailure = useCallback(
		async (actionId: string, error: unknown) => {
			const message =
				error instanceof Error ? error.message : String(error || "");
			setBranchActionErrors((current) => ({
				...current,
				[actionId]:
					message || (isChineseUi ? "分支操作失败。" : "Branch action failed."),
			}));
			const threadState = await client.getThreadState(threadId);
			queryClient.setQueryData(queryKeys.thread(threadId), threadState);
			await refreshBranchActionSurfaces(threadId);
		},
		[client, isChineseUi, queryClient, refreshBranchActionSurfaces, threadId],
	);

	const executeBranchAction = useCallback(
		async (action: FocusAgentBranchActionProposal) => {
			const requestEpoch = beginBranchActionRequest(action.action_id);
			if (requestEpoch === null) {
				return;
			}
			const sourceThreadId = threadId;
			try {
				const result = await retryThreadBusyConflict(
					() => client.executeBranchAction(sourceThreadId, action.action_id),
					() => isCurrentBranchActionRequest(requestEpoch, sourceThreadId),
				);
				if (!isCurrentBranchActionRequest(requestEpoch, sourceThreadId)) {
					return;
				}
				queryClient.setQueryData(
					queryKeys.thread(sourceThreadId),
					result.thread_state,
				);
				await refreshBranchActionSurfaces(sourceThreadId);
				const navigation = navigationFromBranchActionResult(result);
				if (navigation) {
					if (!isCurrentBranchActionRequest(requestEpoch, sourceThreadId)) {
						return;
					}
					const handoffMessage = branchActionHandoffMessage(result);
					await queryClient.invalidateQueries({
						queryKey: queryKeys.thread(navigation.thread_id),
					});
					await navigate({
						to: "/c/$conversationId/t/$threadId",
						params: {
							conversationId: navigation.root_thread_id,
							threadId: navigation.thread_id,
						},
					});
					if (handoffMessage && navigation.thread_id !== sourceThreadId) {
						void options.onRunHandoff?.({
							threadId: navigation.thread_id,
							message: handoffMessage,
						});
					}
				}
			} catch (error) {
				if (
					error instanceof ThreadBranchActionRetryCancelled ||
					!isCurrentBranchActionRequest(requestEpoch, sourceThreadId)
				) {
					return;
				}
				console.error("Failed to execute branch action", error);
				await refreshThreadAfterBranchActionFailure(action.action_id, error);
			} finally {
				if (isCurrentBranchActionRequest(requestEpoch, sourceThreadId)) {
					endBranchActionRequest(action.action_id);
				}
			}
		},
		[
			beginBranchActionRequest,
			client,
			endBranchActionRequest,
			isCurrentBranchActionRequest,
			navigate,
			queryClient,
			refreshBranchActionSurfaces,
			refreshThreadAfterBranchActionFailure,
			options,
			threadId,
		],
	);

	const dismissBranchAction = useCallback(
		async (action: FocusAgentBranchActionProposal) => {
			const requestEpoch = beginBranchActionRequest(action.action_id);
			if (requestEpoch === null) {
				return;
			}
			const sourceThreadId = threadId;
			try {
				const threadState = await retryThreadBusyConflict(
					() => client.dismissBranchAction(sourceThreadId, action.action_id),
					() => isCurrentBranchActionRequest(requestEpoch, sourceThreadId),
				);
				if (!isCurrentBranchActionRequest(requestEpoch, sourceThreadId)) {
					return;
				}
				queryClient.setQueryData(queryKeys.thread(sourceThreadId), threadState);
				await refreshBranchActionSurfaces(sourceThreadId);
			} catch (error) {
				if (
					error instanceof ThreadBranchActionRetryCancelled ||
					!isCurrentBranchActionRequest(requestEpoch, sourceThreadId)
				) {
					return;
				}
				console.error("Failed to dismiss branch action", error);
				await refreshThreadAfterBranchActionFailure(action.action_id, error);
			} finally {
				if (isCurrentBranchActionRequest(requestEpoch, sourceThreadId)) {
					endBranchActionRequest(action.action_id);
				}
			}
		},
		[
			beginBranchActionRequest,
			client,
			endBranchActionRequest,
			isCurrentBranchActionRequest,
			queryClient,
			refreshBranchActionSurfaces,
			refreshThreadAfterBranchActionFailure,
			threadId,
		],
	);

	const continueCurrentBranchAction = useCallback(
		async (action: FocusAgentBranchActionProposal) => {
			const requestEpoch = beginBranchActionRequest(action.action_id);
			if (requestEpoch === null) {
				return;
			}
			const sourceThreadId = threadId;
			try {
				const threadState = await retryThreadBusyConflict(
					() => client.dismissBranchAction(sourceThreadId, action.action_id),
					() => isCurrentBranchActionRequest(requestEpoch, sourceThreadId),
				);
				if (!isCurrentBranchActionRequest(requestEpoch, sourceThreadId)) {
					return;
				}
				queryClient.setQueryData(queryKeys.thread(sourceThreadId), threadState);
				await refreshBranchActionSurfaces(sourceThreadId);
				const handoffMessage = branchActionProposalHandoffMessage(action);
				if (handoffMessage) {
					void options.onContinueCurrentBranch?.({
						threadId: sourceThreadId,
						message: handoffMessage,
					});
				}
			} catch (error) {
				if (
					error instanceof ThreadBranchActionRetryCancelled ||
					!isCurrentBranchActionRequest(requestEpoch, sourceThreadId)
				) {
					return;
				}
				console.error("Failed to continue current branch action", error);
				await refreshThreadAfterBranchActionFailure(action.action_id, error);
			} finally {
				if (isCurrentBranchActionRequest(requestEpoch, sourceThreadId)) {
					endBranchActionRequest(action.action_id);
				}
			}
		},
		[
			beginBranchActionRequest,
			client,
			endBranchActionRequest,
			isCurrentBranchActionRequest,
			options,
			queryClient,
			refreshBranchActionSurfaces,
			refreshThreadAfterBranchActionFailure,
			threadId,
		],
	);

	useEffect(() => {
		branchActionThreadIdRef.current = threadId;
		branchActionRequestEpochRef.current += 1;
		setBranchActionInFlightId(null);
		setBranchActionErrors({});
		branchActionInFlightRef.current = null;
		return () => {
			branchActionRequestEpochRef.current += 1;
			if (branchActionThreadIdRef.current === threadId) {
				branchActionInFlightRef.current = null;
			}
		};
	}, [threadId]);

	return {
		branchActionErrors,
		branchActionInFlightId,
		continueCurrentBranchAction,
		dismissBranchAction,
		executeBranchAction,
	};
}
