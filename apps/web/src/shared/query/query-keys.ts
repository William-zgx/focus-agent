export const queryKeys = {
	principal: ["principal"] as const,
	mySessions: ["my-sessions"] as const,
	models: ["models"] as const,
	conversations: ["conversations"] as const,
	thread: (threadId: string) => ["thread", threadId] as const,
	branchDecisionConfig: ["branch-decision-config"] as const,
	threadBranchDecisions: (threadId: string) =>
		["thread-branch-decisions", threadId] as const,
	branchTrees: ["branch-tree"] as const,
	branchTree: (threadId: string) =>
		["branch-tree", "thread", threadId] as const,
	trajectoryList: (filtersKey: string) =>
		["trajectory-list", filtersKey] as const,
	trajectoryDetail: (turnId: string) => ["trajectory-detail", turnId] as const,
	observabilityOverview: (filtersKey: string) =>
		["observability-overview", filtersKey] as const,
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
	adminUsersRoot: ["admin-users"] as const,
	adminUsers: (filtersKey: string) => ["admin-users", filtersKey] as const,
	adminUser: (userId: string) => ["admin-user", userId] as const,
	adminUserSessions: (userId: string) =>
		["admin-user-sessions", userId] as const,
	adminAuditEventsRoot: ["admin-audit-events"] as const,
	adminAuditEvents: (filtersKey: string) =>
		["admin-audit-events", filtersKey] as const,
	adminConfig: ["admin-config"] as const,
};
