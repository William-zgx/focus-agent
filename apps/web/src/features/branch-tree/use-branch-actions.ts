import type {
  BranchRole,
  FocusAgentApplyMergeDecisionRequest,
  FocusAgentBranchRecord,
} from "@focus-agent/web-sdk";
import { useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

interface BranchScope {
  rootThreadId: string;
  threadId?: string;
}

export function useBranchActions(scope: BranchScope) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();

  async function invalidate(threadId = scope.threadId) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(scope.rootThreadId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
    if (threadId) {
      await queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) });
    }
  }

  async function forkBranch(input: {
    parentThreadId: string;
    branchName?: string;
    branchRole?: BranchRole;
  }): Promise<FocusAgentBranchRecord> {
    const record = await client.forkBranch({
      parent_thread_id: input.parentThreadId,
      branch_name: input.branchName,
      branch_role: input.branchRole,
    });
    await invalidate(input.parentThreadId);
    await queryClient.invalidateQueries({ queryKey: queryKeys.thread(record.child_thread_id) });
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
    const record = await client.renameBranch(threadId, { branch_name: branchName });
    await invalidate(threadId);
    return record;
  }

  async function prepareMergeProposal(threadId: string) {
    const proposal = await client.prepareMergeProposal(threadId);
    await invalidate(threadId);
    return proposal;
  }

  async function applyMergeDecision(threadId: string, request: FocusAgentApplyMergeDecisionRequest) {
    const response = await client.applyMergeDecision(threadId, request);
    await invalidate(threadId);
    await queryClient.invalidateQueries({ queryKey: queryKeys.thread(scope.rootThreadId) });
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
