export const queryKeys = {
  principal: ["principal"] as const,
  models: ["models"] as const,
  conversations: ["conversations"] as const,
  thread: (threadId: string) => ["thread", threadId] as const,
  branchTree: (rootThreadId: string) => ["branch-tree", rootThreadId] as const,
  trajectoryList: (filtersKey: string) => ["trajectory-list", filtersKey] as const,
  trajectoryDetail: (turnId: string) => ["trajectory-detail", turnId] as const,
  trajectoryStats: (filtersKey: string) => ["trajectory-stats", filtersKey] as const,
  observabilityOverview: (filtersKey: string) => ["observability-overview", filtersKey] as const,
  agentRolePolicy: ["agent-role-policy"] as const,
  agentRoleDecisions: (limit: number) => ["agent-role-decisions", limit] as const,
};
