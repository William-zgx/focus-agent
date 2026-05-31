import type {
	BranchRole,
	FocusAgentApplyMergeDecisionRequest,
	FocusAgentBranchRecord,
} from "@focus-agent/web-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import {
	ThreadBranchActionRetryCancelled,
	retryThreadBusyConflict,
} from "@/shared/thread/retry-thread-busy-conflict";

interface BranchScope {
	rootThreadId: string;
	threadId?: string;
}

export function useBranchActions(scope: BranchScope) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();
	const mountedRef = useRef(true);
	const scopeRef = useRef(scope);

	scopeRef.current = scope;

	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
		};
	}, []);

	async function invalidate(threadId = scope.threadId) {
		const tasks = [
			queryClient.invalidateQueries({
				queryKey: queryKeys.branchTrees,
			}),
			queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
		];
		if (threadId) {
			tasks.push(
				queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) }),
			);
		}
		await Promise.all(tasks);
	}

	function invalidateInBackground(threadId = scope.threadId) {
		void invalidate(threadId);
	}

	async function forkBranch(input: {
		parentThreadId: string;
		branchName?: string;
		branchRole?: BranchRole;
		language?: "en" | "zh";
	}): Promise<FocusAgentBranchRecord> {
		const record = await client.forkBranch({
			parent_thread_id: input.parentThreadId,
			branch_name: input.branchName,
			branch_role: input.branchRole,
			language: input.language,
		});
		invalidateInBackground(input.parentThreadId);
		void queryClient.invalidateQueries({
			queryKey: queryKeys.thread(record.child_thread_id),
		});
		return record;
	}

	async function archiveBranch(threadId: string) {
		const record = await client.archiveBranch(threadId);
		await invalidate(threadId);
		return record;
	}

	async function activateBranch(threadId: string) {
		const record = await client.activateBranch(threadId);
		await invalidate(threadId);
		return record;
	}

	async function renameBranch(threadId: string, branchName: string) {
		const record = await client.renameBranch(threadId, {
			branch_name: branchName,
		});
		await invalidate(threadId);
		return record;
	}

	async function prepareMergeProposal(threadId: string) {
		const requestScope = {
			rootThreadId: scopeRef.current.rootThreadId,
			threadId: scopeRef.current.threadId,
		};
		const shouldContinue = () =>
			mountedRef.current &&
			scopeRef.current.rootThreadId === requestScope.rootThreadId &&
			scopeRef.current.threadId === requestScope.threadId;
		const proposal = await retryThreadBusyConflict(
			() => client.prepareMergeProposal(threadId),
			shouldContinue,
		);
		if (!shouldContinue()) {
			throw new ThreadBranchActionRetryCancelled();
		}
		await invalidate(threadId);
		return proposal;
	}

	async function applyMergeDecision(
		threadId: string,
		request: FocusAgentApplyMergeDecisionRequest,
	) {
		const response = await client.applyMergeDecision(threadId, request);
		await invalidate(threadId);
		const targetThreadIds = [scope.rootThreadId];
		if (response.target_thread_id) {
			targetThreadIds.push(response.target_thread_id);
		}
		await Promise.all(
			Array.from(new Set(targetThreadIds)).map((targetThreadId) =>
				queryClient.invalidateQueries({
					queryKey: queryKeys.thread(targetThreadId),
				}),
			),
		);
		return response;
	}

	return {
		forkBranch,
		archiveBranch,
		activateBranch,
		renameBranch,
		prepareMergeProposal,
		applyMergeDecision,
	};
}
