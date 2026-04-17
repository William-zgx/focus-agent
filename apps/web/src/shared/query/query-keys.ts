export const queryKeys = {
  principal: ["principal"] as const,
  models: ["models"] as const,
  conversations: ["conversations"] as const,
  thread: (threadId: string) => ["thread", threadId] as const,
  branchTree: (rootThreadId: string) => ["branch-tree", rootThreadId] as const,
};
