import type {
  FocusAgentBranchActionExecuteResponse,
  FocusAgentBranchActionNavigation,
  FocusAgentBranchActionProposal,
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

export function useThreadBranchActions(threadId: string) {
  const { client } = useFocusAgent();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { isChineseUi } = useShellUi();
  const [branchActionInFlightId, setBranchActionInFlightId] = useState<string | null>(null);
  const [branchActionErrors, setBranchActionErrors] = useState<Record<string, string>>({});
  const branchActionInFlightRef = useRef<string | null>(null);

  const refreshBranchActionSurfaces = useCallback(
    async (rootThreadId: string, currentThreadId: string) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
        queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(rootThreadId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.thread(currentThreadId) }),
      ]);
    },
    [queryClient],
  );

  const beginBranchActionRequest = useCallback((actionId: string) => {
    if (branchActionInFlightRef.current) {
      return false;
    }
    branchActionInFlightRef.current = actionId;
    setBranchActionInFlightId(actionId);
    setBranchActionErrors((current) => {
      const next = { ...current };
      delete next[actionId];
      return next;
    });
    return true;
  }, []);

  const endBranchActionRequest = useCallback((actionId: string) => {
    if (branchActionInFlightRef.current === actionId) {
      branchActionInFlightRef.current = null;
      setBranchActionInFlightId(null);
    }
  }, []);

  const refreshThreadAfterBranchActionFailure = useCallback(
    async (actionId: string, error: unknown) => {
      const message = error instanceof Error ? error.message : String(error || "");
      setBranchActionErrors((current) => ({
        ...current,
        [actionId]: message || (isChineseUi ? "分支操作失败。" : "Branch action failed."),
      }));
      const threadState = await client.getThreadState(threadId);
      queryClient.setQueryData(queryKeys.thread(threadId), threadState);
      await refreshBranchActionSurfaces(threadState.root_thread_id, threadId);
    },
    [client, isChineseUi, queryClient, refreshBranchActionSurfaces, threadId],
  );

  const executeBranchAction = useCallback(
    async (action: FocusAgentBranchActionProposal) => {
      if (!beginBranchActionRequest(action.action_id)) {
        return;
      }
      try {
        const result = await client.executeBranchAction(threadId, action.action_id);
        queryClient.setQueryData(queryKeys.thread(threadId), result.thread_state);
        await refreshBranchActionSurfaces(result.thread_state.root_thread_id, threadId);
        const navigation = navigationFromBranchActionResult(result);
        if (navigation) {
          await queryClient.invalidateQueries({ queryKey: queryKeys.thread(navigation.thread_id) });
          await navigate({
            to: "/c/$conversationId/t/$threadId",
            params: {
              conversationId: navigation.root_thread_id,
              threadId: navigation.thread_id,
            },
          });
        }
      } catch (error) {
        console.error("Failed to execute branch action", error);
        await refreshThreadAfterBranchActionFailure(action.action_id, error);
      } finally {
        endBranchActionRequest(action.action_id);
      }
    },
    [
      beginBranchActionRequest,
      client,
      endBranchActionRequest,
      navigate,
      queryClient,
      refreshBranchActionSurfaces,
      refreshThreadAfterBranchActionFailure,
      threadId,
    ],
  );

  const dismissBranchAction = useCallback(
    async (action: FocusAgentBranchActionProposal) => {
      if (!beginBranchActionRequest(action.action_id)) {
        return;
      }
      try {
        const threadState = await client.dismissBranchAction(threadId, action.action_id);
        queryClient.setQueryData(queryKeys.thread(threadId), threadState);
        await refreshBranchActionSurfaces(threadState.root_thread_id, threadId);
      } catch (error) {
        console.error("Failed to dismiss branch action", error);
        await refreshThreadAfterBranchActionFailure(action.action_id, error);
      } finally {
        endBranchActionRequest(action.action_id);
      }
    },
    [
      beginBranchActionRequest,
      client,
      endBranchActionRequest,
      queryClient,
      refreshBranchActionSurfaces,
      refreshThreadAfterBranchActionFailure,
      threadId,
    ],
  );

  useEffect(() => {
    setBranchActionInFlightId(null);
    setBranchActionErrors({});
    branchActionInFlightRef.current = null;
  }, [threadId]);

  return {
    branchActionErrors,
    branchActionInFlightId,
    dismissBranchAction,
    executeBranchAction,
  };
}
