import { useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useConversationActions() {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();

  async function invalidate(rootThreadId?: string) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
    if (rootThreadId) {
      await queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(rootThreadId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.thread(rootThreadId) });
    }
  }

  async function createConversation(title?: string) {
    const conversation = await client.createConversation(title ? { title } : {});
    await invalidate(conversation.root_thread_id);
    return conversation;
  }

  async function renameConversation(rootThreadId: string, title: string) {
    const conversation = await client.renameConversation(rootThreadId, { title });
    await invalidate(rootThreadId);
    return conversation;
  }

  async function archiveConversation(rootThreadId: string) {
    const conversation = await client.archiveConversation(rootThreadId);
    await invalidate(rootThreadId);
    return conversation;
  }

  async function activateConversation(rootThreadId: string) {
    const conversation = await client.activateConversation(rootThreadId);
    await invalidate(rootThreadId);
    return conversation;
  }

  return {
    createConversation,
    renameConversation,
    archiveConversation,
    activateConversation,
  };
}
