import type {
	ContextUsageResponse,
	FocusAgentAdminConfig,
	FocusAgentAuditEvent,
	FocusAgentBranchDecisionEvent,
	FocusAgentConversationSummary,
	FocusAgentNote,
	FocusAgentSession,
	FocusAgentTask,
	FocusAgentTaskEvent,
	FocusAgentUser,
	ThreadStateResponse,
} from "@focus-agent/web-sdk";

export type { ContextUsageResponse };

export interface LocalRuntimeSequence {
	action: number;
	artifact: number;
	audit: number;
	branch: number;
	memory: number;
	message: number;
	note: number;
	run: number;
	session: number;
	task: number;
	taskEvent: number;
	thread: number;
}

export interface LocalRuntimeState {
	accessMode?: "device-local-single-user";
	version: 1 | 2;
	adminConfig: FocusAgentAdminConfig;
	artifacts?: LocalArtifact[];
	auditEvents: FocusAgentAuditEvent[];
	branchDecisions?: Record<string, FocusAgentBranchDecisionEvent[]>;
	conversations: FocusAgentConversationSummary[];
	forgottenMemoryIds?: string[];
	gitCommits?: LocalGitCommit[];
	memories?: LocalMemory[];
	modelSecrets?: Record<string, { apiKey?: string }>;
	notes: FocusAgentNote[];
	sequence: LocalRuntimeSequence;
	sessions: FocusAgentSession[];
	taskEvents: FocusAgentTaskEvent[];
	tasks: FocusAgentTask[];
	threads: Record<string, ThreadStateResponse>;
	users: FocusAgentUser[];
	workspaceBaseFiles?: Record<string, string>;
	workspaceFiles?: Record<string, string>;
}

export type JsonRecord = Record<string, unknown>;

export interface ChatCompletionMessage {
	role: "assistant" | "system" | "user";
	content: string;
}

export interface LocalModelProvider {
	id: string;
	label: string;
	baseUrl: string;
	apiKey: string;
}

export interface ResolvedLocalModelProvider {
	model: string;
	provider: LocalModelProvider;
}

export type LocalWebSearchTimeRange = "day" | "week" | "month" | "year";

export interface LocalWebSearchResultItem {
	title: string;
	url: string;
	/** Search-provider text used to decide which primary page to read next. */
	snippet: string;
	published_at?: string | null;
	observed_at?: string;
}

export interface LocalWebSearchResult {
	/** Search providers do not author the answer; snippets are evidence leads. */
	answer: string | null;
	attempted_providers?: string[];
	errors?: Array<{
		category: string;
		message: string;
		provider: string;
	}>;
	fallback_used?: boolean;
	query: string;
	results: LocalWebSearchResultItem[];
	observed_at: string;
	search_filters?: {
		time_range: LocalWebSearchTimeRange | null;
		include_domains: string[];
		exclude_domains: string[];
		provider_time_range?: string | null;
		provider_query?: string;
		domain_filter_mode?: "native" | "query_operators" | "unsupported";
	};
	provider?: string;
	source: string;
}

export interface LocalWebFetchResult {
	content: string;
	content_chars?: number;
	content_type: string;
	fetch_limited?: boolean;
	final_url: string;
	offset?: number;
	next_offset?: number | null;
	published_at?: string | null;
	source: string;
	shown_chars?: number;
	title: string;
	total_chars?: number;
	truncated: boolean;
	url: string;
	observed_at?: string;
	continuation?: {
		available: boolean;
		offset?: number;
		limit?: number;
		total_chars?: number;
		hint: string;
	};
}

export interface LocalArtifact {
	artifact_id: string;
	title: string;
	content: string;
	content_type: string;
	created_at: string;
	updated_at: string;
	root_thread_id: string;
	thread_id: string;
}

export interface LocalMemory {
	memory_id: string;
	content: string;
	kind: string;
	scope: "user" | "root_thread";
	visibility: "shared";
	user_id: string | null;
	root_thread_id: string | null;
	tags: string[];
	created_at: string;
	updated_at: string;
	deleted_at: string | null;
}

export interface LocalSkill {
	skill_id: string;
	name: string;
	description: string;
	triggers: string[];
	aliases?: string[];
	localized_triggers?: string[];
	domains?: string[];
	intents?: string[];
	when_to_use: string[];
	primary_tools?: string[];
	recommended_tools: string[];
	prompt_mode: string;
	content: string;
	source_id: string;
}

export interface LocalToolExecution {
	name: string;
	args: Record<string, unknown>;
	message: string;
	output: unknown;
}

export interface LocalGitCommit {
	hash: string;
	subject: string;
	author: string;
	date: string;
}

export interface FocusAgentSecureStoragePlugin {
	get(options: { key: string }): Promise<{ value?: string | null }>;
	remove(options: { key: string }): Promise<void>;
	set(options: { key: string; value: string }): Promise<void>;
}
