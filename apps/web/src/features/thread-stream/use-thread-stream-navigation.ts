import type {
  BranchActionPayload,
  FocusAgentBranchActionNavigation,
} from "@focus-agent/web-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { invalidateBranchActionNavigationSurfaces } from "./use-thread-stream-cache";

export function navigationFromBranchActionPayload(
  payload: BranchActionPayload,
): FocusAgentBranchActionNavigation | null {
  const navigation = payload.navigation ?? payload.branch_action?.navigation;
  if (
    navigation &&
    typeof navigation.root_thread_id === "string" &&
    typeof navigation.thread_id === "string"
  ) {
    return navigation;
  }
  return null;
}

export function useThreadStreamNavigation() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  function handleBranchActionExecuted(payload: BranchActionPayload, sourceThreadId: string) {
    const navigation = navigationFromBranchActionPayload(payload);
    if (!navigation) {
      return;
    }

    invalidateBranchActionNavigationSurfaces(
      queryClient,
      navigation.root_thread_id,
      sourceThreadId,
      navigation.thread_id,
    );
    void navigate({
      to: "/c/$conversationId/t/$threadId",
      params: {
        conversationId: navigation.root_thread_id,
        threadId: navigation.thread_id,
      },
    });
  }

  return { handleBranchActionExecuted };
}
