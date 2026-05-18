export const queryKeys = {
	principal: ["principal"] as const,
	mySessions: ["my-sessions"] as const,
	models: ["models"] as const,
	conversations: ["conversations"] as const,
	thread: (threadId: string) => ["thread", threadId] as const,
	branchDecisionConfig: ["branch-decision-config"] as const,
	threadBranchDecisions: (threadId: string) =>
		["thread-branch-decisions", threadId] as const,
	branchTree: (rootThreadId: string) => ["branch-tree", rootThreadId] as const,
	trajectoryList: (filtersKey: string) =>
		["trajectory-list", filtersKey] as const,
	trajectoryDetail: (turnId: string) => ["trajectory-detail", turnId] as const,
	observabilityOverview: (filtersKey: string) =>
		["observability-overview", filtersKey] as const,
	agentRolePolicy: ["agent-role-policy"] as const,
	agentRoleDecisions: (limit: number) =>
		["agent-role-decisions", limit] as const,
	agentCapabilities: ["agent-capabilities"] as const,
	agentToolRouteDecisions: (limit: number) =>
		["agent-tool-route-decisions", limit] as const,
	agentMemoryCuratorPolicy: ["agent-memory-curator-policy"] as const,
	agentMemoryCuratorDecisions: (limit: number) =>
		["agent-memory-curator-decisions", limit] as const,
	agentDelegationPolicy: ["agent-delegation-policy"] as const,
	agentDelegationRuns: (limit: number) =>
		["agent-delegation-runs", limit] as const,
	agentModelRouterPolicy: ["agent-model-router-policy"] as const,
	agentModelRouterDecisions: (limit: number) =>
		["agent-model-router-decisions", limit] as const,
	agentSelfRepairFailures: (limit: number) =>
		["agent-self-repair-failures", limit] as const,
	agentReviewQueue: (limit: number) => ["agent-review-queue", limit] as const,
	agentContextPolicy: ["agent-context-policy"] as const,
	agentContextDecisions: (limit: number) =>
		["agent-context-decisions", limit] as const,
	agentContextArtifacts: (limit: number) =>
		["agent-context-artifacts", limit] as const,
	agentContextEvidence: (filtersKey: string) =>
		["agent-context-evidence", filtersKey] as const,
	agentSkillCatalog: ["agent-skill-catalog"] as const,
	agentSkillSelections: (limit: number) =>
		["agent-skill-selections", limit] as const,
	agentFeedbackTrend: ["agent-feedback-trend"] as const,
	agentTaskLedgerPolicy: ["agent-task-ledger-policy"] as const,
	agentTaskLedgerRuns: (limit: number) =>
		["agent-task-ledger-runs", limit] as const,
	agentArtifacts: (limit: number) => ["agent-artifacts", limit] as const,
	agentCriticVerdicts: (limit: number) =>
		["agent-critic-verdicts", limit] as const,
	memoryRecordsRoot: ["memory-records"] as const,
	memoryRecords: (filtersKey: string) =>
		["memory-records", filtersKey] as const,
	memoryAuditRoot: ["memory-audit"] as const,
	memoryAudit: (filtersKey: string) => ["memory-audit", filtersKey] as const,
	memoryCandidatesRoot: ["memory-candidates"] as const,
	memoryCandidates: (filtersKey: string) =>
		["memory-candidates", filtersKey] as const,
	productivityNotesRoot: ["productivity-notes"] as const,
	productivityNotes: (filtersKey: string) =>
		["productivity-notes", filtersKey] as const,
	productivityTasksRoot: ["productivity-tasks"] as const,
	productivityTasks: (filtersKey: string) =>
		["productivity-tasks", filtersKey] as const,
	agentTeamSessions: (filtersKey: string) =>
		["agent-team-sessions", filtersKey] as const,
	agentTeamSession: (sessionId: string) =>
		["agent-team-session", sessionId] as const,
	agentTeamMergeReviews: (sessionId: string) =>
		["agent-team-merge-reviews", sessionId] as const,
	agentTeamToolApprovals: (sessionId: string) =>
		["agent-team-tool-approvals", sessionId] as const,
	adminUsersRoot: ["admin-users"] as const,
	adminUsers: (filtersKey: string) => ["admin-users", filtersKey] as const,
	adminUser: (userId: string) => ["admin-user", userId] as const,
	adminUserSessions: (userId: string) =>
		["admin-user-sessions", userId] as const,
	adminAuditEventsRoot: ["admin-audit-events"] as const,
	adminAuditEvents: (filtersKey: string) =>
		["admin-audit-events", filtersKey] as const,
};
