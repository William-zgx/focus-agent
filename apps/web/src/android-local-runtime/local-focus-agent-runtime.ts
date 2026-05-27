import type {
	BranchTreeNode,
	BranchTreeResponse,
	ContextUsageResponse,
	FocusAgentAdminConfig,
	FocusAgentApplyMergeDecisionRequest,
	FocusAgentApplyMergeDecisionResponse,
	FocusAgentAuditEvent,
	FocusAgentAuditEventListResponse,
	FocusAgentAuthResponse,
	FocusAgentBranchActionExecuteResponse,
	FocusAgentBranchActionProposal,
	FocusAgentBranchDecisionConfig,
	FocusAgentBranchDecisionEvent,
	FocusAgentBranchDecisionListResponse,
	FocusAgentBranchDecisionSummary,
	FocusAgentBranchRecord,
	FocusAgentConversationListResponse,
	FocusAgentConversationSummary,
	FocusAgentCreateNoteRequest,
	FocusAgentCreateConversationRequest,
	FocusAgentCreateTaskRequest,
	FocusAgentCreateUserRequest,
	FocusAgentEvent,
	FocusAgentForkBranchRequest,
	FocusAgentHarnessRunCancelRequest,
	FocusAgentHarnessRunRequest,
	FocusAgentHarnessRunResponse,
	FocusAgentLoginRequest,
	FocusAgentMergeProposal,
	FocusAgentModelOption,
	FocusAgentModelsResponse,
	FocusAgentNote,
	FocusAgentNoteListResponse,
	FocusAgentNoteResponse,
	FocusAgentPrincipalResponse,
	FocusAgentProductivitySourceKind,
	FocusAgentRenameBranchRequest,
	FocusAgentSession,
	FocusAgentSessionListResponse,
	FocusAgentTask,
	FocusAgentTaskEvent,
	FocusAgentTaskEventListResponse,
	FocusAgentTaskListResponse,
	FocusAgentTaskResponse,
	FocusAgentTaskStatus,
	FocusAgentUpdateAdminModelConfigRequest,
	FocusAgentUpdateAdminPolicyConfigRequest,
	FocusAgentUpdateAdminToolConfigRequest,
	FocusAgentUpdateConversationRequest,
	FocusAgentUpdateNoteRequest,
	FocusAgentUpdateTaskRequest,
	FocusAgentUpdateUserRequest,
	FocusAgentUpdateUserRolesRequest,
	FocusAgentUpdateUserStatusRequest,
	FocusAgentUser,
	FocusAgentUserListResponse,
	MergeMode,
	ThreadContextPreviewRequest,
	ThreadContextPreviewResponse,
	ThreadResolution,
	ThreadStateResponse,
} from "@focus-agent/web-sdk";
import {
	Capacitor,
	CapacitorHttp,
	registerPlugin,
	type HttpHeaders,
} from "@capacitor/core";

const STORAGE_KEY = "focus-agent-android-local-runtime-state";
const SECRET_STORAGE_KEY = "focus-agent-android-local-runtime-model-secrets";
const SECRET_STORAGE_FALLBACK_KEY =
	"focus-agent-android-local-runtime-model-secrets-fallback";
const LOCAL_USER_ID = "android-local-admin";
const LOCAL_TENANT_ID = "android-local";
const DEFAULT_PROVIDER_ID = "deepseek";
const DEFAULT_PROVIDER_BASE_URL = "https://api.deepseek.com";
const DEFAULT_MODEL_ID = "deepseek-v4-pro";
const LOCAL_WEB_SEARCH_USER_AGENT =
	"FocusAgentAndroid/1.0 (+https://focus-agent.local)";
const ANDROID_LOCAL_TOOL_NAMES = [
	"write_text_artifact",
	"artifact_list",
	"artifact_read",
	"artifact_update",
	"memory_save",
	"memory_search",
	"memory_forget",
	"conversation_summary",
	"skills_list",
	"skill_view",
	"skill_sources",
	"skills_search",
	"web_fetch",
	"web_search",
	"current_utc_time",
	"list_files",
	"read_file",
	"search_code",
	"codebase_stats",
	"apply_patch",
	"run_workspace_command",
	"git_status",
	"git_diff",
	"git_log",
	"skill_install",
	"skills_refresh_index",
] as const;
const ANDROID_LOCAL_TOOL_NAME_SET = new Set<string>(ANDROID_LOCAL_TOOL_NAMES);
const JSON_HEADERS = { "Content-Type": "application/json" };
const SSE_HEADERS = {
	"Cache-Control": "no-cache",
	"Content-Type": "text/event-stream",
};

interface LocalRuntimeSequence {
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

interface LocalRuntimeState {
	version: 1;
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

type JsonRecord = Record<string, unknown>;

interface ChatCompletionMessage {
	role: "assistant" | "system" | "user";
	content: string;
}

interface LocalModelProvider {
	id: string;
	label: string;
	baseUrl: string;
	apiKey: string;
}

interface ResolvedLocalModelProvider {
	model: string;
	provider: LocalModelProvider;
}

interface LocalWebSearchResult {
	answer: string;
	attempted_providers?: string[];
	errors?: Array<{
		category: string;
		message: string;
		provider: string;
	}>;
	fallback_used?: boolean;
	query: string;
	results: Array<{
		title: string;
		url: string;
		snippet: string;
	}>;
	source: string;
}

interface LocalWebFetchResult {
	content: string;
	content_type: string;
	final_url: string;
	source: string;
	title: string;
	truncated: boolean;
	url: string;
}

interface LocalArtifact {
	artifact_id: string;
	title: string;
	content: string;
	content_type: string;
	created_at: string;
	updated_at: string;
	root_thread_id: string;
	thread_id: string;
}

interface LocalMemory {
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

interface LocalSkill {
	skill_id: string;
	name: string;
	description: string;
	triggers: string[];
	when_to_use: string[];
	recommended_tools: string[];
	prompt_mode: string;
	content: string;
	source_id: string;
}

interface LocalToolExecution {
	name: string;
	args: Record<string, unknown>;
	message: string;
	output: unknown;
}

interface LocalGitCommit {
	hash: string;
	subject: string;
	author: string;
	date: string;
}

interface FocusAgentSecureStoragePlugin {
	get(options: { key: string }): Promise<{ value?: string | null }>;
	remove(options: { key: string }): Promise<void>;
	set(options: { key: string; value: string }): Promise<void>;
}

const focusAgentSecureStorage = registerPlugin<FocusAgentSecureStoragePlugin>(
	"FocusAgentSecureStorage",
);

function nowIso(): string {
	return new Date().toISOString();
}

function id(prefix: string, value: number): string {
	return `${prefix}-${String(value).padStart(4, "0")}`;
}

function clone<T>(value: T): T {
	return JSON.parse(JSON.stringify(value)) as T;
}

function isRecord(value: unknown): value is JsonRecord {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseJsonBody(init?: RequestInit): unknown {
	const body = init?.body;
	if (!body || typeof body !== "string") return {};
	try {
		return JSON.parse(body) as unknown;
	} catch {
		return {};
	}
}

function stringValue(value: unknown): string {
	return typeof value === "string" ? value : "";
}

function nullableString(value: unknown): string | null {
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function stringArray(value: unknown): string[] {
	return Array.isArray(value)
		? value.filter((item): item is string => typeof item === "string")
		: [];
}

function metadataRecord(value: unknown): Record<string, unknown> {
	return isRecord(value) ? value : {};
}

function searchParamBoolean(
	searchParams: URLSearchParams,
	key: string,
	fallback = false,
): boolean {
	const value = searchParams.get(key);
	if (value === null || value === "") return fallback;
	return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

function searchParamNumber(
	searchParams: URLSearchParams,
	key: string,
	fallback: number,
): number {
	const value = Number(searchParams.get(key) ?? fallback);
	return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function normalizedUrl(value: string | null | undefined): string {
	const trimmedValue = value?.trim();
	if (!trimmedValue) return "";
	try {
		const url = new URL(trimmedValue);
		url.pathname = url.pathname.replace(/\/+$/, "");
		url.search = "";
		url.hash = "";
		return url.toString().replace(/\/$/, "");
	} catch {
		return "";
	}
}

function chatCompletionsUrl(baseUrl: string): string {
	const normalized = normalizedUrl(baseUrl) || DEFAULT_PROVIDER_BASE_URL;
	return normalized.endsWith("/chat/completions")
		? normalized
		: `${normalized}/chat/completions`;
}

function routeSegments(pathname: string): string[] {
	return pathname
		.split("/")
		.filter(Boolean)
		.map((part) => decodeURIComponent(part));
}

function jsonResponse(data: unknown, init: ResponseInit = {}): Response {
	return new Response(JSON.stringify(data), {
		...init,
		headers: { ...JSON_HEADERS, ...init.headers },
	});
}

function emptyResponse(init: ResponseInit = {}): Response {
	return new Response(null, init);
}

function errorResponse(status: number, message: string): Response {
	return jsonResponse(
		{
			detail: {
				code: status,
				message,
				stable_code: status,
			},
		},
		{ status },
	);
}

function contextUsage(
	messages: Array<Record<string, unknown>>,
): ContextUsageResponse {
	const promptChars = messages.reduce(
		(total, message) => total + String(message.content ?? "").length,
		0,
	);
	const usedTokens = Math.max(0, Math.ceil(promptChars / 4));
	const tokenLimit = 32000;
	const usedRatio = usedTokens / tokenLimit;
	return {
		used_tokens: usedTokens,
		token_limit: tokenLimit,
		remaining_tokens: Math.max(0, tokenLimit - usedTokens),
		used_ratio: usedRatio,
		status:
			usedRatio >= 1
				? "over"
				: usedRatio >= 0.85
					? "hot"
					: usedRatio >= 0.65
						? "warm"
						: "ok",
		prompt_chars: promptChars,
		prompt_budget_chars: tokenLimit * 4,
		tokenizer_mode: "local-estimate",
	};
}

function localUser(overrides: Partial<FocusAgentUser> = {}): FocusAgentUser {
	const timestamp = nowIso();
	return {
		user_id: LOCAL_USER_ID,
		username: "android-local",
		display_name: "Android Local Admin",
		email: "local@focus-agent.invalid",
		tenant_id: LOCAL_TENANT_ID,
		status: "active",
		roles: ["admin"],
		auth_provider: "local-runtime",
		created_at: timestamp,
		updated_at: timestamp,
		last_seen_at: timestamp,
		last_login_at: timestamp,
		password_updated_at: timestamp,
		metadata: { runtime: "android-local" },
		...overrides,
	};
}

function defaultWorkspaceFiles(): Record<string, string> {
	return {
		"README.md": [
			"# Focus Agent Android Local Workspace",
			"",
			"This is an app-local virtual workspace used when Focus Agent runs on Android without a backend.",
			"It supports local file listing, reading, code search, patching, and virtual git inspection.",
			"",
		].join("\n"),
		"docs/android-local-runtime.md": [
			"# Android Local Runtime",
			"",
			"- Chat, branches, admin configuration, model provider keys, web_search, web_fetch, memory, artifacts, and observability run inside the app.",
			"- Agent Team is intentionally disabled on Android.",
			"- Productivity notes and tasks are intentionally hidden on Android.",
			"",
		].join("\n"),
		"src/app.ts": [
			"export function runtimeMode() {",
			'  return "android-local";',
			"}",
			"",
			"export const enabledCapabilities = [",
			'  "chat",',
			'  "branches",',
			'  "web_search",',
			'  "web_fetch",',
			'  "artifacts",',
			'  "memory",',
			'  "workspace",',
			"];",
			"",
		].join("\n"),
	};
}

function defaultGitCommits(timestamp = nowIso()): LocalGitCommit[] {
	return [
		{
			hash: "androidlocal0001",
			subject: "Initialize Android local workspace",
			author: "Focus Agent Android",
			date: timestamp,
		},
	];
}

function principal(user: FocusAgentUser): FocusAgentPrincipalResponse {
	return {
		user_id: user.user_id,
		tenant_id: user.tenant_id,
		scopes: ["chat", "branches", "admin"],
		auth_enabled: false,
		user,
		roles: user.roles,
		permissions: ["chat:write", "branches:write", "admin:write"],
		is_admin: user.roles.includes("admin"),
	};
}

function authResponse(user: FocusAgentUser): FocusAgentAuthResponse {
	return {
		access_token: "android-local-token",
		token_type: "bearer",
		refresh_token: "android-local-refresh",
		expires_in_seconds: 86400,
		issuer: "focus-agent-android-local-runtime",
		principal: principal(user),
		user,
		session: null,
	};
}

function modelOption(): FocusAgentModelOption {
	return {
		id: DEFAULT_MODEL_ID,
		provider: DEFAULT_PROVIDER_ID,
		provider_label: "DeepSeek",
		provider_logo_slug: null,
		provider_logo_letter: "D",
		name: DEFAULT_MODEL_ID,
		label: DEFAULT_MODEL_ID,
		is_default: true,
		supports_thinking: false,
		default_thinking_enabled: false,
	};
}

function configSource() {
	return {
		path: "android-local-runtime",
		exists: true,
		writable: true,
	};
}

function localAdminTool(
	name: string,
	label: string,
	description: string,
	toolset: string,
	options: {
		enabled?: boolean;
		requiresWorkspace?: boolean;
		requiresWorkspaceWrite?: boolean;
		settings?: Record<string, unknown>;
		sideEffect?: boolean;
	} = {},
): FocusAgentAdminConfig["tools"]["tools"][number] {
	return {
		name,
		label,
		description,
		enabled: options.enabled ?? true,
		settings: options.settings ?? {},
		metadata: {
			runtime: "android-local",
			toolset,
			requires_workspace: Boolean(options.requiresWorkspace),
			requires_workspace_write: Boolean(options.requiresWorkspaceWrite),
			side_effect: Boolean(options.sideEffect),
			unavailable_reason:
				options.enabled === false
					? "This tool needs a Focus Agent workspace backend and is disabled in the Android app-local runtime."
					: null,
		},
	};
}

function defaultAdminConfig(): FocusAgentAdminConfig {
	const model = modelOption();
	return {
		models: {
			source: configSource(),
			default_model: model.id,
			helper_model: model.id,
			model_choices: [model.id],
			providers: [
				{
					id: DEFAULT_PROVIDER_ID,
					label: "DeepSeek",
					backend_provider: "openai-compatible",
					aliases: [DEFAULT_PROVIDER_ID, "openai-compatible"],
					logo_slug: model.provider_logo_slug,
					logo_letter: model.provider_logo_letter,
					base_url_env: null,
					base_url_default: DEFAULT_PROVIDER_BASE_URL,
					base_url_configured: true,
					api_key_env: null,
					api_key_configured: false,
				},
			],
			models: [
				{
					id: model.id,
					label: model.label,
					supports_thinking: model.supports_thinking,
					default_thinking_enabled: model.default_thinking_enabled,
					request_kwargs: {},
					thinking_enabled_request_kwargs: {},
					thinking_disabled_request_kwargs: {},
					thinking_disabled_model_name: null,
					reasoning_effort: null,
					no_temperature: true,
					thinking_enable_extra_body_type: null,
					thinking_disable_extra_body_type: null,
					thinking_disable_switch_model: null,
				},
			],
			requires_restart: false,
		},
		tools: {
			source: configSource(),
			tools: [
				localAdminTool(
					"write_text_artifact",
					"写入文本产物",
					"在 Android 本地运行时中把文本保存为 App 内产物。",
					"artifact",
					{ sideEffect: true },
				),
				localAdminTool(
					"artifact_list",
					"产物列表",
					"列出 Android 本地运行时保存的 App 内产物。",
					"artifact",
				),
				localAdminTool(
					"artifact_read",
					"读取产物",
					"读取 Android 本地运行时保存的 App 内产物。",
					"artifact",
				),
				localAdminTool(
					"artifact_update",
					"更新产物",
					"替换、追加或前置更新 Android 本地运行时保存的 App 内产物。",
					"artifact",
					{ sideEffect: true },
				),
				localAdminTool(
					"memory_save",
					"保存记忆",
					"把用户确认的事实保存到 Android 本地记忆。",
					"memory",
					{ sideEffect: true },
				),
				localAdminTool(
					"memory_search",
					"搜索记忆",
					"搜索 Android 本地会话派生记忆。",
					"memory",
				),
				localAdminTool(
					"memory_forget",
					"遗忘记忆",
					"在 Android 本地运行时中遗忘一条本地记忆。",
					"memory",
					{ sideEffect: true },
				),
				localAdminTool(
					"conversation_summary",
					"会话摘要",
					"返回 Android 本地线程的滚动摘要和最近消息。",
					"conversation",
				),
				localAdminTool(
					"skills_list",
					"技能列表",
					"列出 Android 本地运行时可见的技能目录。",
					"skills",
				),
				localAdminTool(
					"skill_view",
					"查看技能",
					"查看 Android 本地运行时中的技能详情。",
					"skills",
				),
				localAdminTool(
					"skill_sources",
					"技能来源",
					"列出 Android 本地运行时的技能来源。",
					"skills",
				),
				localAdminTool(
					"skills_search",
					"搜索技能",
					"搜索 Android 本地运行时可见的技能目录。",
					"skills",
				),
				localAdminTool(
					"web_fetch",
					"网页抓取",
					"在 Android 本地运行时中抓取公开网页内容，并把可读正文作为工具上下文提供给模型。",
					"web",
					{
						settings: {
							default_max_chars: 5000,
							max_chars_cap: 12000,
						},
					},
				),
				localAdminTool(
					"web_search",
					"网页搜索",
					"在 Android 本地运行时中执行实时网页搜索，并把结果作为工具上下文提供给模型。",
					"web",
					{
						settings: {
							provider: "duckduckgo",
							fallback_provider: null,
							api_key_env: null,
							api_key_configured: false,
						},
					},
				),
				localAdminTool(
					"current_utc_time",
					"当前 UTC 时间",
					"为实时网页搜索提供当前时间锚点。",
					"web",
				),
				localAdminTool(
					"list_files",
					"列出文件",
					"列出 Android App 内虚拟工作区文件。",
					"workspace",
				),
				localAdminTool(
					"read_file",
					"读取文件",
					"读取 Android App 内虚拟工作区文件。",
					"workspace",
				),
				localAdminTool(
					"search_code",
					"搜索代码",
					"搜索 Android App 内虚拟工作区文本内容。",
					"workspace",
				),
				localAdminTool(
					"codebase_stats",
					"代码库统计",
					"统计 Android App 内虚拟工作区文件和语言分布。",
					"workspace",
				),
				localAdminTool(
					"apply_patch",
					"应用补丁",
					"把 unified diff 应用到 Android App 内虚拟工作区。",
					"workspace",
					{ requiresWorkspaceWrite: true, sideEffect: true },
				),
				localAdminTool(
					"run_workspace_command",
					"运行工作区命令",
					"在 Android App 内虚拟工作区执行安全的只读命令模拟。",
					"workspace",
					{ requiresWorkspaceWrite: true, sideEffect: true },
				),
				localAdminTool(
					"git_status",
					"Git 状态",
					"查看 Android App 内虚拟工作区相对初始快照的 Git 状态。",
					"git",
				),
				localAdminTool(
					"git_diff",
					"Git 差异",
					"查看 Android App 内虚拟工作区相对初始快照的 diff。",
					"git",
				),
				localAdminTool(
					"git_log",
					"Git 日志",
					"查看 Android App 内虚拟工作区的本地提交日志。",
					"git",
				),
				localAdminTool(
					"skill_install",
					"安装技能",
					"把 Android App 内置技能标记为本地可用。",
					"skills",
					{ sideEffect: true },
				),
				localAdminTool(
					"skills_refresh_index",
					"刷新技能索引",
					"刷新 Android App 内置技能目录索引。",
					"skills",
					{ sideEffect: true },
				),
			],
			providers: [
				{
					id: "android-local-web",
					enabled: true,
					order: 1,
					metadata: { runtime: "android-local" },
					overrides: [],
				},
			],
			requires_restart: false,
		},
		policies: {
			source: configSource(),
			items: [],
			requires_restart: false,
		},
		system: {
			source: configSource(),
			items: [
				{
					key: "runtime",
					env_key: null,
					label: "Runtime",
					value: "android-local",
					value_type: "string",
					source: "local",
					editable: false,
					sensitive: false,
					configured: true,
					requires_restart: false,
					description: "Android in-app local runtime.",
					options: [],
				},
			],
		},
		updated_at: nowIso(),
		updated_by: LOCAL_USER_ID,
		message: "Android local runtime is active.",
	};
}

function newThreadState(
	threadId: string,
	rootThreadId: string,
): ThreadStateResponse {
	const messages: Array<Record<string, unknown>> = [];
	return {
		thread_id: threadId,
		root_thread_id: rootThreadId,
		assistant_message: null,
		rolling_summary: "",
		selected_model: DEFAULT_MODEL_ID,
		selected_thinking_mode: "disabled",
		branch_meta: null,
		merge_proposal: null,
		merge_decision: null,
		merge_queue: [],
		active_skill_ids: [],
		messages,
		interrupts: [],
		branch_actions: [],
		branch_decision_summary: null,
		trace: {},
		context_usage: contextUsage(messages),
	};
}

function initialState(): LocalRuntimeState {
	const timestamp = nowIso();
	const user = localUser({
		created_at: timestamp,
		updated_at: timestamp,
		last_seen_at: timestamp,
		last_login_at: timestamp,
		password_updated_at: timestamp,
	});
	const rootThreadId = "local-thread-0001";
	const rootThread = newThreadState(rootThreadId, rootThreadId);
	const workspaceFiles = defaultWorkspaceFiles();
	const session: FocusAgentSession = {
		session_id: "local-session-0001",
		user_id: user.user_id,
		created_at: timestamp,
		updated_at: timestamp,
		expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
		revoked_at: null,
		last_seen_at: timestamp,
		user_agent: "Focus Agent Android local runtime",
		ip_address: null,
		metadata: { runtime: "android-local" },
		current: true,
	};
	return {
		version: 1,
		adminConfig: defaultAdminConfig(),
		artifacts: [],
		auditEvents: [],
		branchDecisions: {},
		conversations: [
			{
				root_thread_id: rootThreadId,
				title: "Local Android Chat",
				is_archived: false,
				archived_at: null,
				created_at: timestamp,
				updated_at: timestamp,
			},
		],
		forgottenMemoryIds: [],
		gitCommits: defaultGitCommits(timestamp),
		memories: [],
		notes: [],
		sequence: {
			action: 1,
			artifact: 1,
			audit: 1,
			branch: 1,
			memory: 1,
			message: 1,
			note: 1,
			run: 1,
			session: 2,
			task: 1,
			taskEvent: 1,
			thread: 2,
		},
		sessions: [session],
		taskEvents: [],
		tasks: [],
		threads: { [rootThreadId]: rootThread },
		users: [user],
		workspaceBaseFiles: clone(workspaceFiles),
		workspaceFiles,
	};
}

function normalizeStoredState(value: LocalRuntimeState): LocalRuntimeState {
	value.artifacts = Array.isArray(value.artifacts) ? value.artifacts : [];
	value.branchDecisions = isRecord(value.branchDecisions)
		? Object.fromEntries(
				Object.entries(value.branchDecisions).map(([threadId, decisions]) => [
					threadId,
					Array.isArray(decisions) ? decisions : [],
				]),
			)
		: {};
	value.notes = Array.isArray(value.notes) ? value.notes : [];
	value.forgottenMemoryIds = Array.isArray(value.forgottenMemoryIds)
		? value.forgottenMemoryIds
		: [];
	value.gitCommits = Array.isArray(value.gitCommits)
		? value.gitCommits
		: defaultGitCommits();
	value.memories = Array.isArray(value.memories) ? value.memories : [];
	value.taskEvents = Array.isArray(value.taskEvents) ? value.taskEvents : [];
	value.tasks = Array.isArray(value.tasks) ? value.tasks : [];
	const defaultTools = defaultAdminConfig().tools.tools;
	value.adminConfig.tools.tools = value.adminConfig.tools.tools.filter((tool) =>
		ANDROID_LOCAL_TOOL_NAME_SET.has(tool.name),
	);
	for (const defaultTool of defaultTools) {
		if (
			!value.adminConfig.tools.tools.some(
				(tool) => tool.name === defaultTool.name,
			)
		) {
			value.adminConfig.tools.tools.push(defaultTool);
		}
	}
	const appLocalWorkspaceTools = new Set([
		"list_files",
		"read_file",
		"search_code",
		"codebase_stats",
		"apply_patch",
		"run_workspace_command",
		"git_status",
		"git_diff",
		"git_log",
		"skill_install",
		"skills_refresh_index",
	]);
	value.adminConfig.tools.tools = value.adminConfig.tools.tools.map((tool) => {
		const defaultTool = defaultTools.find((item) => item.name === tool.name);
		if (defaultTool && appLocalWorkspaceTools.has(tool.name)) {
			return defaultTool;
		}
		return tool;
	});
	value.sequence.artifact ??= value.artifacts.length + 1;
	value.sequence.memory ??= value.memories.length + 1;
	value.sequence.note ??= value.notes.length + 1;
	value.sequence.task ??= value.tasks.length + 1;
	value.sequence.taskEvent ??= value.taskEvents.length + 1;
	value.workspaceFiles = isRecord(value.workspaceFiles)
		? Object.fromEntries(
				Object.entries(value.workspaceFiles).filter(
					(entry): entry is [string, string] => typeof entry[1] === "string",
				),
			)
		: defaultWorkspaceFiles();
	value.workspaceBaseFiles = isRecord(value.workspaceBaseFiles)
		? Object.fromEntries(
				Object.entries(value.workspaceBaseFiles).filter(
					(entry): entry is [string, string] => typeof entry[1] === "string",
				),
			)
		: clone(value.workspaceFiles);
	return value;
}

function threadBranchRecord(
	thread: ThreadStateResponse,
): FocusAgentBranchRecord | null {
	const meta = thread.branch_meta;
	if (!meta) return null;
	return {
		branch_id: meta.branch_id,
		root_thread_id: meta.root_thread_id,
		parent_thread_id: meta.parent_thread_id,
		child_thread_id: thread.thread_id,
		return_thread_id: meta.return_thread_id,
		owner_user_id: LOCAL_USER_ID,
		branch_name: meta.branch_name,
		branch_role: meta.branch_role,
		branch_depth: meta.branch_depth,
		branch_status: meta.branch_status,
		is_archived: Boolean(meta.is_archived),
		archived_at: meta.archived_at ?? null,
		fork_checkpoint_id: meta.fork_checkpoint_id ?? null,
		fork_strategy: meta.fork_strategy,
		merge_proposal: thread.merge_proposal ?? null,
		merge_decision: thread.merge_decision ?? null,
	};
}

function localReply(message: string): string {
	const trimmedMessage = message.trim();
	const isChinese = /[\u3400-\u9fff]/.test(trimmedMessage);
	if (isChinese) {
		return [
			"本地 Android 运行时已处理这条消息。",
			"",
			trimmedMessage
				? `你刚才说：${trimmedMessage}`
				: "这次请求没有包含新的用户消息。",
			"",
			"当前构建不会连接 Focus Agent 后端；对话、分支、账号和管理数据都保存在 App 本地。",
		].join("\n");
	}
	return [
		"The Android local runtime handled this turn.",
		"",
		trimmedMessage
			? `You said: ${trimmedMessage}`
			: "This request did not include a new user message.",
		"",
		"This build does not connect to the Focus Agent backend; chat, branch, account, and admin data stay inside the app.",
	].join("\n");
}

function splitText(text: string, maxChunkLength = 48): string[] {
	const chunks: string[] = [];
	for (let index = 0; index < text.length; index += maxChunkLength) {
		chunks.push(text.slice(index, index + maxChunkLength));
	}
	return chunks.length ? chunks : [""];
}

function textWords(text: string): string[] {
	const normalized = text.toLowerCase();
	const latinTerms = normalized.match(/[a-z0-9][a-z0-9_-]{2,}/g) ?? [];
	const hanChars = normalized.match(/\p{Script=Han}/gu) ?? [];
	const hanTerms = hanChars.flatMap((char, index) =>
		hanChars[index + 1] ? [`${char}${hanChars[index + 1]}`] : [],
	);
	return [...new Set([...latinTerms, ...hanTerms])];
}

function containsAny(text: string, patterns: string[]): boolean {
	const normalized = text.toLowerCase();
	return patterns.some((pattern) => normalized.includes(pattern));
}

function suggestedBranchName(message: string, isChinese: boolean): string {
	const compact = message.replace(/\s+/g, " ").trim();
	if (!compact) return isChinese ? "本地分支" : "Local branch";
	const prefix = isChinese ? "探索：" : "Explore: ";
	return `${prefix}${compact.slice(0, 48)}`;
}

function localBranchHandoffMessage(message: string): string | null {
	const compact = message.replace(/\s+/g, " ").trim();
	return compact || null;
}

function slugifyArtifactTitle(title: string): string {
	const cleaned = title
		.trim()
		.toLowerCase()
		.replace(/[^\p{Letter}\p{Number}\s_-]+/gu, "")
		.replace(/\s+/g, "-")
		.replace(/-+/g, "-")
		.replace(/^-|-$/g, "");
	return `${cleaned || "artifact"}.md`;
}

function quotedText(message: string): string | null {
	const match =
		message.match(/["“”']([^"“”']{2,})["“”']/u) ??
		message.match(/《([^》]{2,})》/u);
	return match?.[1]?.trim() ?? null;
}

function afterCue(message: string, cues: string[]): string | null {
	const normalized = message.replace(/\s+/g, " ").trim();
	for (const cue of cues) {
		const index = normalized.toLowerCase().indexOf(cue.toLowerCase());
		if (index < 0) continue;
		const value = normalized.slice(index + cue.length).trim();
		if (value) return value;
	}
	return null;
}

const ANDROID_LOCAL_SKILLS: LocalSkill[] = [
	{
		skill_id: "android-local-runtime",
		name: "android-local-runtime",
		description:
			"Run Focus Agent chat, admin, branches, and tools inside the Android app.",
		triggers: ["android", "mobile", "local runtime"],
		when_to_use: [
			"The user wants to understand what the Android app can do without a Focus Agent backend.",
		],
		recommended_tools: ["conversation_summary", "web_search", "memory_search"],
		prompt_mode: "answer",
		content:
			"Use local app state first. Do not claim access to a Focus Agent backend, workspace shell, or Git checkout.",
		source_id: "android-local",
	},
	{
		skill_id: "branch-focus-score",
		name: "branch-focus-score",
		description: "Explain and use local Focus Score branch recommendations.",
		triggers: ["branch", "focus score", "推荐分支", "分支"],
		when_to_use: [
			"The user asks whether a turn should continue current context or branch.",
		],
		recommended_tools: ["conversation_summary"],
		prompt_mode: "answer",
		content:
			"Use the Android local Focus Score decision and pending branch action when topic drift is detected.",
		source_id: "android-local",
	},
	{
		skill_id: "local-artifacts-memory",
		name: "local-artifacts-memory",
		description: "Use app-local artifacts and durable local memory.",
		triggers: ["artifact", "memory", "产物", "记忆"],
		when_to_use: [
			"The user asks to save, read, update, remember, search, or forget local information.",
		],
		recommended_tools: [
			"write_text_artifact",
			"artifact_list",
			"memory_save",
			"memory_search",
		],
		prompt_mode: "execute",
		content:
			"Persist only app-local artifacts and memories. Keep productivity notes/tasks out of Android.",
		source_id: "android-local",
	},
	{
		skill_id: "local-web-tools",
		name: "local-web-tools",
		description:
			"Search or fetch public web content directly from the Android app.",
		triggers: ["web", "search", "fetch", "网页搜索", "抓取"],
		when_to_use: [
			"The user asks for current, recent, online, or URL-specific information.",
		],
		recommended_tools: ["current_utc_time", "web_search", "web_fetch"],
		prompt_mode: "execute",
		content:
			"Use current_utc_time for temporal queries, web_search for open lookup, and web_fetch for a specific URL.",
		source_id: "android-local",
	},
];

function shouldUseWebSearch(message: string): boolean {
	const compact = message.replace(/\s+/g, " ").trim();
	if (!compact) return false;
	if (
		containsAny(compact, [
			"不要联网",
			"不用联网",
			"不要搜索",
			"无需搜索",
			"不用搜",
			"别联网",
			"别搜",
			"no web",
			"no search",
			"without searching",
		])
	) {
		return false;
	}
	return containsAny(compact, [
		"web search",
		"search the web",
		"search online",
		"look up",
		"latest",
		"recent",
		"today",
		"current",
		"news",
		"weather",
		"stock",
		"price",
		"网页搜索",
		"联网搜索",
		"联网查",
		"网上查",
		"网上搜",
		"全网查",
		"全网搜",
		"搜索一下",
		"搜一下",
		"搜搜",
		"帮我搜",
		"查一下",
		"查查",
		"最新",
		"最近",
		"今天",
		"今日",
		"现在",
		"实时",
		"新闻",
		"天气",
		"股价",
		"价格",
	]);
}

function shouldUseCurrentTimeTool(message: string): boolean {
	return containsAny(message, [
		"latest",
		"recent",
		"today",
		"current",
		"now",
		"this week",
		"this month",
		"最新",
		"最近",
		"今天",
		"当前",
		"现在",
		"本周",
		"本月",
	]);
}

function searchQueryCore(message: string): string {
	let query = message.replace(/\s+/g, " ").trim();
	query = query
		.replace(
			/^(?:请|帮我|帮忙|麻烦你|麻烦|可以|能不能|please)?\s*(?:联网|上网|网上|全网|web)?\s*(?:搜索|搜|查|查询|检索|search(?: the web)?(?: for)?|look up)\s*(?:一下|下)?[：:,，]?\s*/iu,
			"",
		)
		.replace(
			/\s*(?:，|,)?\s*(?:请)?(?:联网|上网|网上|全网)?\s*(?:搜索|搜|查|查询|检索)(?:一下|下|查)?[。.!！?？]*$/u,
			"",
		)
		.replace(
			/\s*(?:please\s+)?(?:search|look up|search the web)(?:\s+it)?[.!?]*$/iu,
			"",
		)
		.replace(
			/\s*(?:请)?(?:给出?|附上|提供)?(?:来源|出处|source|sources|citation|citations)[。.!！?？]*$/iu,
			"",
		)
		.replace(/\s*(?:怎么样|如何|是什么|是多少|是啥)[。.!！?？]*$/u, "")
		.replace(/[。.!！?？]+$/u, "")
		.trim();
	return query || message.replace(/\s+/g, " ").trim();
}

function requiresTemporalAnchor(message: string): boolean {
	return containsAny(message, [
		"今天",
		"今日",
		"明天",
		"昨天",
		"本周",
		"这周",
		"近一周",
		"最近",
		"近期",
		"过去一周",
		"现在",
		"当前",
		"实时",
		"today",
		"tomorrow",
		"yesterday",
		"this week",
		"recent",
		"recently",
		"last 7 days",
		"past week",
		"now",
		"current",
	]);
}

function relativeDateParts(query: string, currentUtcTime: string): string[] {
	const anchor = new Date(currentUtcTime);
	if (Number.isNaN(anchor.getTime())) return [];
	const anchorDate = anchor.toISOString().slice(0, 10);
	const anchorMs = Date.UTC(
		anchor.getUTCFullYear(),
		anchor.getUTCMonth(),
		anchor.getUTCDate(),
	);
	const dateAfterDays = (days: number) =>
		new Date(anchorMs + days * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
	const parts: string[] = [];
	if (
		containsAny(query, [
			"今天",
			"今日",
			"today",
			"现在",
			"当前",
			"current",
			"now",
		])
	) {
		parts.push(`绝对日期(今天/UTC)：${anchorDate}`);
	}
	if (containsAny(query, ["明天", "tomorrow"])) {
		parts.push(`绝对日期(明天/UTC)：${dateAfterDays(1)}`);
	}
	if (containsAny(query, ["昨天", "yesterday"])) {
		parts.push(`绝对日期(昨天/UTC)：${dateAfterDays(-1)}`);
	}
	if (
		containsAny(query, [
			"近一周",
			"最近一周",
			"过去一周",
			"last 7 days",
			"past week",
			"recent",
		])
	) {
		parts.push(
			`绝对时间范围(近一周/UTC)：${dateAfterDays(-6)} 至 ${anchorDate}`,
		);
	}
	return [...new Set(parts)];
}

function searchLocationScope(query: string): string {
	const patterns = [
		/(?:今天|今日|明天|昨天|本周|这周|近一周|最近|近期)\s*([\u4e00-\u9fffA-Za-z][\w\u4e00-\u9fff\s·.-]{1,24}?)(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)/u,
		/([\u4e00-\u9fff]{2,12})(?:今天|今日|明天|昨天|本周|这周|近一周|最近|近期).{0,12}(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)/u,
		/(?:访问|到访|访华)([\u4e00-\u9fff]{2,12})/u,
		/\b(?:in|for|at)\s+([a-z][a-z .'-]{1,40}?)(?:\s+(?:today|tomorrow|this week|weather|news|stock|price)|[?.!,]|$)/i,
	];
	for (const pattern of patterns) {
		const match = query.match(pattern);
		const value = match?.[1]
			?.replace(
				/^(?:帮我|请|查一下|查下|搜一下|搜索|看一下|看看|一下|有哪个|哪个|哪些|the)\s*/iu,
				"",
			)
			.replace(/\s+/g, " ")
			.trim()
			.replace(/[，。,.?!？]+$/u, "");
		if (value) return value.slice(0, 40);
	}
	return "";
}

function webSearchQuery(
	message: string,
	currentUtcTime?: string | null,
): string {
	const query = searchQueryCore(message).slice(0, 180);
	if (!currentUtcTime || !requiresTemporalAnchor(query))
		return query.slice(0, 240);
	const dateParts = relativeDateParts(query, currentUtcTime);
	if (!dateParts.length) return query.slice(0, 240);
	const normalizedUtcTime = new Date(currentUtcTime).toISOString();
	const locationScope = searchLocationScope(query);
	const metadata = [
		`原始查询：${query}`,
		`当前UTC时间：${normalizedUtcTime}`,
		...dateParts,
		locationScope ? `地点/范围：${locationScope}` : "地点/范围：见原始查询",
	];
	return `${query}（${metadata.join("; ")}）`.slice(0, 360);
}

function webFetchUrl(message: string): string {
	return (
		message.match(/https?:\/\/[^\s<>"'，。；;、)）\]]+/i)?.[0] ?? ""
	).replace(/[.,，。;；:：!?！？]+$/u, "");
}

function shouldUseWebFetch(message: string): boolean {
	if (!webFetchUrl(message)) return false;
	const normalized = message.toLowerCase();
	return containsAny(normalized, [
		"web_fetch",
		"fetch",
		"open",
		"read this url",
		"read the url",
		"page content",
		"抓取",
		"读取",
		"打开",
		"访问",
		"网页",
		"页面",
		"链接",
	]);
}

function compactWebSearchSummary(result: LocalWebSearchResult): string {
	const lines = result.results.slice(0, 3).map((item, index) => {
		const url = item.url ? ` (${item.url})` : "";
		return `${index + 1}. ${item.title}${url}: ${item.snippet}`;
	});
	return [result.answer, ...lines].filter(Boolean).join("\n");
}

function compactWebFetchSummary(result: LocalWebFetchResult): string {
	return [
		result.title ? `${result.title} (${result.final_url})` : result.final_url,
		result.content,
	]
		.filter(Boolean)
		.join("\n")
		.slice(0, 1800);
}

function localReplyWithWebSearch(
	message: string,
	searchResult: LocalWebSearchResult,
): string {
	const isChinese = /[\u3400-\u9fff]/.test(message);
	const summary = compactWebSearchSummary(searchResult);
	if (isChinese) {
		return [
			"我已在 Android 本地运行时执行网页搜索，并基于搜索结果给出回答。",
			"",
			summary || `搜索请求：${searchResult.query}`,
		].join("\n");
	}
	return [
		"I ran a web search in the Android local runtime and answered from the search results.",
		"",
		summary || `Search query: ${searchResult.query}`,
	].join("\n");
}

function localReplyWithWebFetch(
	message: string,
	fetchResult: LocalWebFetchResult,
): string {
	const isChinese = /[\u3400-\u9fff]/.test(message);
	const summary = compactWebFetchSummary(fetchResult);
	if (isChinese) {
		return [
			"我已在 Android 本地运行时抓取网页，并基于页面内容给出回答。",
			"",
			summary || `抓取地址：${fetchResult.final_url}`,
		].join("\n");
	}
	return [
		"I fetched the page in the Android local runtime and answered from its content.",
		"",
		summary || `Fetched URL: ${fetchResult.final_url}`,
	].join("\n");
}

function deniesExecutedWebAccess(reply: string): boolean {
	const compact = reply.replace(/\s+/g, " ").trim();
	if (!compact) return false;
	return containsAny(compact, [
		"无法联网",
		"不能联网",
		"无法直接联网",
		"无法进行实时网络查询",
		"无法直接进行实时网络查询",
		"不能进行实时网络查询",
		"无法实时查询",
		"不能实时查询",
		"无法直接获取实时",
		"无法获取实时",
		"不能获取实时",
		"无法直接访问互联网",
		"不能直接访问互联网",
		"cannot browse",
		"can't browse",
		"cannot search the web",
		"can't search the web",
		"cannot access the internet",
		"can't access the internet",
		"unable to access the internet",
		"cannot access real-time",
		"can't access real-time",
		"unable to access real-time",
	]);
}

function localReplyWithLocalTools(
	message: string,
	executions: LocalToolExecution[],
): string {
	const isChinese = /[\u3400-\u9fff]/.test(message);
	const summary = executions
		.map((execution) => {
			const output =
				typeof execution.output === "string"
					? execution.output
					: JSON.stringify(execution.output);
			return `- ${execution.name}: ${execution.message}\n${output.slice(0, 1000)}`;
		})
		.join("\n");
	return isChinese
		? ["我已在 Android 本地运行时执行 App 内工具。", "", summary].join("\n")
		: ["I ran the requested Android app-local tools.", "", summary].join("\n");
}

function sseFrame(event: FocusAgentEvent): string {
	const idLine = event.id ? `id: ${event.id}\n` : "";
	return `${idLine}event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`;
}

function sseResponse(
	events: FocusAgentEvent[],
	signal?: AbortSignal,
): Response {
	const encoder = new TextEncoder();
	const body = new ReadableStream<Uint8Array>({
		start(controller) {
			let index = 0;
			let timeout: ReturnType<typeof setTimeout> | null = null;

			const close = () => {
				if (timeout) {
					clearTimeout(timeout);
					timeout = null;
				}
			};
			const push = () => {
				if (signal?.aborted) {
					close();
					controller.error(
						signal.reason ?? new DOMException("Aborted", "AbortError"),
					);
					return;
				}
				const event = events[index];
				if (!event) {
					close();
					controller.close();
					return;
				}
				controller.enqueue(encoder.encode(sseFrame(event)));
				index += 1;
				timeout = setTimeout(push, 20);
			};

			signal?.addEventListener(
				"abort",
				() => {
					close();
					controller.error(
						signal.reason ?? new DOMException("Aborted", "AbortError"),
					);
				},
				{ once: true },
			);
			push();
		},
	});
	return new Response(body, { headers: SSE_HEADERS });
}

function providerErrorMessage(error: unknown, isChinese: boolean): string {
	const detail = error instanceof Error ? error.message : String(error);
	return isChinese
		? `模型供应商请求失败：${detail}`
		: `The model provider request failed: ${detail}`;
}

function missingProviderKeyReply(
	providerLabel: string,
	isChinese: boolean,
): string {
	return isChinese
		? [
				"Android 本地运行时已启动，但还没有配置模型 API Key。",
				"",
				`请在管理栏 -> 配置中心 -> 模型 Provider 中为 ${providerLabel} 填入 API Key 后保存。`,
				"",
				"当前 App 不会连接 Focus Agent 后端；配置会保存在本机 App 数据里。",
			].join("\n")
		: [
				"The Android local runtime is active, but no model API key is configured yet.",
				"",
				`Open Admin -> Config Center -> Model providers and save an API key for ${providerLabel}.`,
				"",
				"This app does not connect to a Focus Agent backend; config is stored in local app data.",
			].join("\n");
}

function contentPartToText(part: unknown): string {
	if (typeof part === "string") return part;
	if (!isRecord(part)) return "";
	if (typeof part.text === "string") return part.text;
	if (typeof part.content === "string") return part.content;
	return "";
}

function extractAssistantContent(data: unknown): string {
	if (!isRecord(data)) return "";
	const choices = Array.isArray(data.choices) ? data.choices : [];
	const [firstChoice] = choices;
	if (!isRecord(firstChoice) || !isRecord(firstChoice.message)) return "";
	const content = firstChoice.message.content;
	if (typeof content === "string") return content;
	if (Array.isArray(content)) {
		return content.map(contentPartToText).join("").trim();
	}
	return "";
}

function abortIfRequested(signal?: AbortSignal): void {
	if (signal?.aborted) {
		throw signal.reason ?? new DOMException("Aborted", "AbortError");
	}
}

function parseModelSecrets(
	value: string | null | undefined,
): Record<string, { apiKey?: string }> {
	if (!value?.trim()) return {};
	try {
		const parsed = JSON.parse(value) as unknown;
		if (!isRecord(parsed)) return {};
		const secrets: Record<string, { apiKey?: string }> = {};
		for (const [providerId, secret] of Object.entries(parsed)) {
			if (!isRecord(secret) || typeof secret.apiKey !== "string") continue;
			secrets[providerId] = { apiKey: secret.apiKey };
		}
		return secrets;
	} catch {
		return {};
	}
}

async function readSecureModelSecrets(): Promise<
	Record<string, { apiKey?: string }>
> {
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("FocusAgentSecureStorage")
	) {
		const result = await focusAgentSecureStorage.get({
			key: SECRET_STORAGE_KEY,
		});
		return parseModelSecrets(result.value);
	}
	if (Capacitor.isNativePlatform()) return {};
	try {
		return parseModelSecrets(
			window.localStorage.getItem(SECRET_STORAGE_FALLBACK_KEY),
		);
	} catch {
		return {};
	}
}

async function writeSecureModelSecrets(
	secrets: Record<string, { apiKey?: string }>,
): Promise<void> {
	const serialized = JSON.stringify(secrets);
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("FocusAgentSecureStorage")
	) {
		await focusAgentSecureStorage.set({
			key: SECRET_STORAGE_KEY,
			value: serialized,
		});
		return;
	}
	if (Capacitor.isNativePlatform()) {
		throw new Error("Focus Agent secure storage plugin is unavailable.");
	}
	try {
		window.localStorage.setItem(SECRET_STORAGE_FALLBACK_KEY, serialized);
	} catch (error) {
		console.warn(
			"Failed to persist Android local runtime model secrets",
			error,
		);
	}
}

async function postOpenAiCompatibleChatCompletion({
	messages,
	model,
	provider,
	signal,
}: {
	messages: ChatCompletionMessage[];
	model: string;
	provider: LocalModelProvider;
	signal?: AbortSignal;
}): Promise<string> {
	abortIfRequested(signal);
	const url = chatCompletionsUrl(provider.baseUrl);
	const headers: HttpHeaders = {
		Authorization: `Bearer ${provider.apiKey}`,
		"Content-Type": "application/json",
	};
	const data = {
		model,
		messages,
		stream: false,
	};
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("CapacitorHttp")
	) {
		const response = await CapacitorHttp.post({
			url,
			headers,
			data,
			responseType: "json",
			connectTimeout: 30000,
			readTimeout: 120000,
		});
		abortIfRequested(signal);
		if (response.status < 200 || response.status >= 300) {
			throw new Error(`HTTP ${response.status}`);
		}
		const content = extractAssistantContent(response.data);
		if (!content) throw new Error("Provider returned an empty response.");
		return content;
	}

	const response = await fetch(url, {
		body: JSON.stringify(data),
		headers,
		method: "POST",
		signal,
	});
	abortIfRequested(signal);
	const responseBody = (await response.json().catch(() => ({}))) as unknown;
	if (!response.ok) {
		const detail =
			isRecord(responseBody) && typeof responseBody.error === "object"
				? JSON.stringify(responseBody.error)
				: response.statusText;
		throw new Error(`HTTP ${response.status}: ${detail}`);
	}
	const content = extractAssistantContent(responseBody);
	if (!content) throw new Error("Provider returned an empty response.");
	return content;
}

function htmlEntityDecoded(value: string): string {
	const namedEntities: Record<string, string> = {
		amp: "&",
		gt: ">",
		lt: "<",
		nbsp: " ",
		quot: '"',
	};
	return value
		.replace(/&#(x[0-9a-f]+|\d+);/gi, (match, rawCode: string) => {
			const codePoint = rawCode.toLowerCase().startsWith("x")
				? Number.parseInt(rawCode.slice(1), 16)
				: Number.parseInt(rawCode, 10);
			return Number.isInteger(codePoint) &&
				codePoint >= 0 &&
				codePoint <= 0x10ffff
				? String.fromCodePoint(codePoint)
				: match;
		})
		.replace(/&([a-z]+);/gi, (match, entity: string) => {
			return namedEntities[entity.toLowerCase()] ?? match;
		});
}

function readableHtmlFragment(value: string): string {
	return htmlEntityDecoded(value.replace(/<[^>]+>/g, " "))
		.replace(/\s+/g, " ")
		.trim();
}

function htmlAttributeValue(tag: string, attributeName: string): string {
	const match = tag.match(
		new RegExp(`${attributeName}\\s*=\\s*(['"])(.*?)\\1`, "i"),
	);
	return htmlEntityDecoded(match?.[2] ?? "").trim();
}

function normalizedDuckDuckGoHref(rawHref: string): string {
	const href = htmlEntityDecoded(rawHref).trim();
	if (!href) return "";
	const absoluteHref = href.startsWith("//") ? `https:${href}` : href;
	try {
		const url = new URL(absoluteHref, "https://duckduckgo.com");
		return url.searchParams.get("uddg") ?? url.toString();
	} catch {
		return href;
	}
}

function collectDuckDuckGoHtmlResults(
	html: string,
	pattern: RegExp,
	maxResults: number,
): LocalWebSearchResult["results"] {
	const results: LocalWebSearchResult["results"] = [];
	const seen = new Set<string>();
	for (const match of html.matchAll(pattern)) {
		const linkTag = match[1] ?? "";
		const snippetTag = match[2] ?? "";
		const title = readableHtmlFragment(linkTag);
		const url = normalizedDuckDuckGoHref(htmlAttributeValue(linkTag, "href"));
		const snippet = readableHtmlFragment(snippetTag);
		const key = url || `${title}:${snippet}`;
		if (!title || !key || seen.has(key)) continue;
		seen.add(key);
		results.push({
			title: title.slice(0, 180),
			url,
			snippet: (snippet || title).slice(0, 600),
		});
		if (results.length >= maxResults) break;
	}
	return results;
}

function parseDuckDuckGoHtmlResults(
	html: string,
	maxResults: number,
): LocalWebSearchResult["results"] {
	const desktopResults = collectDuckDuckGoHtmlResults(
		html,
		/(<a\b[^>]*class=["'][^"']*\bresult__a\b[^"']*["'][^>]*>[\s\S]*?<\/a>)[\s\S]*?(<a\b[^>]*class=["'][^"']*\bresult__snippet\b[^"']*["'][^>]*>[\s\S]*?<\/a>)/gi,
		maxResults,
	);
	if (desktopResults.length) return desktopResults;
	return collectDuckDuckGoHtmlResults(
		html,
		/(<a\b[^>]*class=["'][^"']*\bresult-link\b[^"']*["'][^>]*>[\s\S]*?<\/a>)[\s\S]*?(<td\b[^>]*class=["'][^"']*\bresult-snippet\b[^"']*["'][^>]*>[\s\S]*?<\/td>)/gi,
		maxResults,
	);
}

async function localWebTextRequest(
	url: string,
	signal?: AbortSignal,
): Promise<string> {
	abortIfRequested(signal);
	const headers: HttpHeaders = {
		Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
		"User-Agent": LOCAL_WEB_SEARCH_USER_AGENT,
	};
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("CapacitorHttp")
	) {
		const response = await CapacitorHttp.get({
			url,
			headers,
			responseType: "text",
			connectTimeout: 15000,
			readTimeout: 30000,
		});
		abortIfRequested(signal);
		if (response.status < 200 || response.status >= 300) {
			throw new Error(`HTTP ${response.status}`);
		}
		return typeof response.data === "string"
			? response.data
			: JSON.stringify(response.data ?? "");
	}
	const webHeaders = new Headers(headers);
	webHeaders.delete("User-Agent");
	const response = await fetch(url, { headers: webHeaders, signal });
	abortIfRequested(signal);
	const text = await response.text();
	if (!response.ok) {
		throw new Error(`HTTP ${response.status}: ${response.statusText}`);
	}
	return text;
}

async function localWebJsonRequest(
	url: string,
	signal?: AbortSignal,
): Promise<unknown> {
	abortIfRequested(signal);
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("CapacitorHttp")
	) {
		const response = await CapacitorHttp.get({
			url,
			responseType: "json",
			connectTimeout: 15000,
			readTimeout: 30000,
		});
		abortIfRequested(signal);
		if (response.status < 200 || response.status >= 300) {
			throw new Error(`HTTP ${response.status}`);
		}
		if (typeof response.data === "string") {
			return JSON.parse(response.data) as unknown;
		}
		return response.data;
	}
	const response = await fetch(url, { signal });
	abortIfRequested(signal);
	const payload = await response.json().catch(() => ({}));
	if (!response.ok) {
		throw new Error(`HTTP ${response.status}: ${response.statusText}`);
	}
	return payload;
}

async function runDuckDuckGoHtmlSearch({
	endpoint,
	query,
	signal,
	source,
}: {
	endpoint: "html" | "lite";
	query: string;
	signal?: AbortSignal;
	source: string;
}): Promise<LocalWebSearchResult> {
	const url = `https://duckduckgo.com/${endpoint}/?${new URLSearchParams({
		q: query,
	}).toString()}`;
	const html = await localWebTextRequest(url, signal);
	const results = parseDuckDuckGoHtmlResults(html, 5);
	if (!results.length) {
		throw new Error(`${source} returned no results.`);
	}
	return {
		answer: results[0]?.snippet || results[0]?.title || "",
		query,
		results,
		source,
	};
}

function duckDuckGoInstantAnswerItems(
	items: unknown[],
): LocalWebSearchResult["results"] {
	return items.flatMap((item): LocalWebSearchResult["results"] => {
		if (!isRecord(item)) return [];
		const nestedTopics = Array.isArray(item.Topics) ? item.Topics : null;
		if (nestedTopics) return duckDuckGoInstantAnswerItems(nestedTopics);
		const text = stringValue(item.Text);
		const title = stringValue(item.Title) || text.split(" - ")[0] || "";
		const url = stringValue(item.FirstURL) || stringValue(item.URL);
		if (!text && !title) return [];
		return [
			{
				title: (title || "Related result").slice(0, 180),
				url,
				snippet: (text || title).slice(0, 600),
			},
		];
	});
}

async function runDuckDuckGoInstantAnswerSearch(
	query: string,
	signal?: AbortSignal,
): Promise<LocalWebSearchResult> {
	const url = `https://api.duckduckgo.com/?${new URLSearchParams({
		format: "json",
		no_html: "1",
		no_redirect: "1",
		q: query,
		skip_disambig: "1",
	}).toString()}`;
	const payload = await localWebJsonRequest(url, signal);
	const record = isRecord(payload) ? payload : {};
	const heading = stringValue(record.Heading);
	const answerText = stringValue(record.Answer);
	const abstractText = stringValue(record.AbstractText);
	const abstractUrl = stringValue(record.AbstractURL);
	const relatedTopics = Array.isArray(record.RelatedTopics)
		? record.RelatedTopics
		: [];
	const directResults = Array.isArray(record.Results) ? record.Results : [];
	const normalizedResults = [
		...(abstractText || answerText || heading
			? [
					{
						title: heading || query,
						url: abstractUrl,
						snippet: abstractText || answerText || heading,
					},
				]
			: []),
		...duckDuckGoInstantAnswerItems(directResults),
		...duckDuckGoInstantAnswerItems(relatedTopics),
	].slice(0, 5);
	if (!normalizedResults.length) {
		throw new Error("duckduckgo_instant_answer returned no results.");
	}
	return {
		answer: abstractText || answerText || normalizedResults[0]?.snippet || "",
		query,
		results: normalizedResults,
		source: "duckduckgo_instant_answer",
	};
}

function localWebSearchError(
	provider: string,
	error: unknown,
): { category: string; message: string; provider: string } {
	const message = error instanceof Error ? error.message : String(error);
	return {
		category: message.includes("returned no results")
			? "empty_results"
			: "provider_error",
		message,
		provider,
	};
}

async function runLocalWebSearch(
	query: string,
	signal?: AbortSignal,
): Promise<LocalWebSearchResult> {
	abortIfRequested(signal);
	const normalizedQuery = query.replace(/\s+/g, " ").trim();
	if (!normalizedQuery) throw new Error("Query must not be empty.");
	const providers = [
		{
			name: "duckduckgo_html",
			run: () =>
				runDuckDuckGoHtmlSearch({
					endpoint: "html",
					query: normalizedQuery,
					signal,
					source: "duckduckgo_html",
				}),
		},
		{
			name: "duckduckgo_lite",
			run: () =>
				runDuckDuckGoHtmlSearch({
					endpoint: "lite",
					query: normalizedQuery,
					signal,
					source: "duckduckgo_lite",
				}),
		},
		{
			name: "duckduckgo_instant_answer",
			run: () => runDuckDuckGoInstantAnswerSearch(normalizedQuery, signal),
		},
	];
	const attemptedProviders: string[] = [];
	const errors: LocalWebSearchResult["errors"] = [];
	for (const provider of providers) {
		attemptedProviders.push(provider.name);
		try {
			const result = await provider.run();
			return {
				...result,
				attempted_providers: attemptedProviders,
				errors,
				fallback_used: provider.name !== providers[0]?.name,
			};
		} catch (error) {
			abortIfRequested(signal);
			errors.push(localWebSearchError(provider.name, error));
		}
	}
	throw new Error(
		`No web search provider succeeded: ${errors
			.map((error) => `${error.provider} (${error.category}): ${error.message}`)
			.join("; ")}`,
	);
}

function readablePageText(value: string): { content: string; title: string } {
	const title = stringValue(
		value.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1],
	)
		.replace(/<[^>]+>/g, " ")
		.replace(/\s+/g, " ")
		.trim();
	const content = value
		.replace(/<script[\s\S]*?<\/script>/gi, " ")
		.replace(/<style[\s\S]*?<\/style>/gi, " ")
		.replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
		.replace(/<[^>]+>/g, " ")
		.replace(/&nbsp;/gi, " ")
		.replace(/&amp;/gi, "&")
		.replace(/&lt;/gi, "<")
		.replace(/&gt;/gi, ">")
		.replace(/&quot;/gi, '"')
		.replace(/&#39;/gi, "'")
		.replace(/\s+/g, " ")
		.trim();
	return { content, title };
}

async function runLocalWebFetch(
	url: string,
	signal?: AbortSignal,
	maxChars = 5000,
): Promise<LocalWebFetchResult> {
	abortIfRequested(signal);
	const parsed = new URL(url);
	if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
		throw new Error("web_fetch only supports http and https URLs.");
	}
	let rawText = "";
	let contentType = "";
	let finalUrl = parsed.toString();
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("CapacitorHttp")
	) {
		const response = await CapacitorHttp.get({
			url: finalUrl,
			responseType: "text",
			connectTimeout: 15000,
			readTimeout: 30000,
		});
		abortIfRequested(signal);
		if (response.status < 200 || response.status >= 300) {
			throw new Error(`HTTP ${response.status}`);
		}
		rawText =
			typeof response.data === "string"
				? response.data
				: JSON.stringify(response.data ?? "");
		contentType = stringValue(
			(response.headers as Record<string, unknown> | undefined)?.[
				"content-type"
			] ??
				(response.headers as Record<string, unknown> | undefined)?.[
					"Content-Type"
				],
		);
		finalUrl = stringValue((response as { url?: unknown }).url) || finalUrl;
	} else {
		const response = await fetch(finalUrl, { signal });
		abortIfRequested(signal);
		if (!response.ok) {
			throw new Error(`HTTP ${response.status}: ${response.statusText}`);
		}
		contentType = response.headers.get("content-type") ?? "";
		finalUrl = response.url || finalUrl;
		rawText = await response.text();
	}
	const isHtml =
		/html/i.test(contentType) || /<html[\s>]/i.test(rawText.slice(0, 500));
	const readable = isHtml
		? readablePageText(rawText)
		: { content: rawText, title: "" };
	const content = readable.content.slice(0, maxChars);
	return {
		content,
		content_type: contentType,
		final_url: finalUrl,
		source: "android_local_web_fetch",
		title: readable.title,
		truncated: readable.content.length > maxChars,
		url,
	};
}

export function createLocalFocusAgentFetch(): typeof fetch {
	const runtime = new LocalFocusAgentRuntime();
	return ((input, init) => runtime.fetch(input, init)) as typeof fetch;
}

class LocalFocusAgentRuntime {
	private modelSecrets: Record<string, { apiKey?: string }> = {};
	private secretsReady: Promise<void> | null = null;
	private state = this.loadState();

	async fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
		if (init?.signal?.aborted) {
			throw init.signal.reason ?? new DOMException("Aborted", "AbortError");
		}
		const requestUrl =
			input instanceof Request
				? input.url
				: input instanceof URL
					? input.href
					: input;
		const url = new URL(requestUrl, window.location.origin);
		const method = (
			init?.method ?? (input instanceof Request ? input.method : "GET")
		).toUpperCase();
		const segments = routeSegments(url.pathname);
		await this.ensureSecrets();

		if (segments[0] === "v1") {
			return this.handleV1(method, segments.slice(1), url.searchParams, init);
		}
		if (segments[0] === "v2") {
			return this.handleV2(method, segments.slice(1), init);
		}
		return errorResponse(404, "Unsupported local runtime endpoint.");
	}

	private loadState(): LocalRuntimeState {
		try {
			const raw = window.localStorage.getItem(STORAGE_KEY);
			if (!raw) return initialState();
			const parsed = JSON.parse(raw) as LocalRuntimeState;
			if (parsed?.version !== 1 || !parsed.threads || !parsed.conversations) {
				return initialState();
			}
			return normalizeStoredState(parsed);
		} catch {
			return initialState();
		}
	}

	private persist(): void {
		try {
			const { modelSecrets: _legacyModelSecrets, ...persistedState } =
				this.state;
			window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persistedState));
		} catch (error) {
			console.warn("Failed to persist Android local runtime state", error);
		}
	}

	private async ensureSecrets(): Promise<void> {
		this.secretsReady ??= this.loadSecrets();
		return this.secretsReady;
	}

	private async loadSecrets(): Promise<void> {
		const storedSecrets = await readSecureModelSecrets();
		const legacySecrets = this.state.modelSecrets ?? {};
		this.modelSecrets = { ...legacySecrets, ...storedSecrets };
		if (this.state.modelSecrets) {
			delete this.state.modelSecrets;
			this.persist();
			await this.persistSecrets();
		}
	}

	private async persistSecrets(): Promise<void> {
		await writeSecureModelSecrets(this.modelSecrets);
	}

	private nextId(prefix: keyof LocalRuntimeSequence, label: string): string {
		const value = this.state.sequence[prefix];
		this.state.sequence[prefix] += 1;
		return id(label, value);
	}

	private currentUser(): FocusAgentUser {
		let user = this.state.users.find((item) => item.user_id === LOCAL_USER_ID);
		if (!user) {
			user = localUser();
			this.state.users.unshift(user);
			this.persist();
		}
		user.last_seen_at = nowIso();
		return user;
	}

	private addAuditEvent(
		action: string,
		resourceType: string,
		resourceId?: string | null,
		metadata: JsonRecord = {},
	): void {
		this.state.auditEvents.unshift({
			event_id: this.nextId("audit", "local-audit"),
			actor_user_id: LOCAL_USER_ID,
			tenant_id: LOCAL_TENANT_ID,
			action,
			resource_type: resourceType,
			resource_id: resourceId ?? null,
			decision: "allowed",
			reason: "android-local-runtime",
			metadata,
			request_id: null,
			created_at: nowIso(),
		});
	}

	private localAgentEmptyList(limit = 50) {
		return {
			items: [],
			count: 0,
			trajectory_available: true,
			trajectory_error: null,
			limit,
		};
	}

	private localTool(name: string) {
		if (!ANDROID_LOCAL_TOOL_NAME_SET.has(name)) return null;
		return (
			this.state.adminConfig.tools.tools.find((tool) => tool.name === name) ??
			defaultAdminConfig().tools.tools.find((tool) => tool.name === name) ??
			null
		);
	}

	private localEnabledTools() {
		return ANDROID_LOCAL_TOOL_NAMES.flatMap((name) => {
			const tool = this.localTool(name);
			return tool?.enabled === false ? [] : tool ? [tool] : [];
		});
	}

	private localToolEnabled(name: string): boolean {
		return Boolean(this.localTool(name)?.enabled);
	}

	private localCapabilities() {
		return this.localEnabledTools().map((tool) => ({
			name: tool.name,
			description: tool.description,
			toolset: String(tool.metadata.toolset ?? "web"),
			allowed_roles: ["planner", "executor", "critic"],
			risk_level: "low",
			side_effect: Boolean(tool.metadata.side_effect),
			parallel_safe: true,
			cacheable: false,
			requires_network: tool.name === "web_search" || tool.name === "web_fetch",
			requires_workspace_write: Boolean(tool.metadata.requires_workspace_write),
			requires_approval: false,
			sensitive_args: [],
			redaction_policy: "none",
			provider_id: "android-local-web",
		}));
	}

	private localRolePolicy() {
		const model =
			this.state.adminConfig.models.default_model ||
			this.state.adminConfig.models.model_choices[0] ||
			DEFAULT_MODEL_ID;
		return {
			enabled: true,
			default_model: model,
			helper_model: this.state.adminConfig.models.helper_model ?? model,
			max_parallel_runs: 1,
			roles: ["planner", "executor", "critic"],
			role_models: {
				planner: model,
				executor: model,
				critic: model,
			},
			fallback_order: ["planner", "executor", "critic"],
		};
	}

	private localRoleDecision(message: string, role = "planner") {
		const model =
			this.state.adminConfig.models.default_model ||
			this.state.adminConfig.models.model_choices[0] ||
			DEFAULT_MODEL_ID;
		return {
			role,
			model_id: model,
			rationale:
				"Android local runtime uses the selected local model for governance previews.",
			route_reason: "android-local-runtime",
			confidence: message.trim() ? 0.72 : 0.5,
			tool_governance: {
				available_tools: this.localCapabilities().map((item) => item.name),
				runtime: "android-local",
			},
		};
	}

	private localSkillCatalogItems() {
		return ANDROID_LOCAL_SKILLS.map((skill) => ({
			skill_id: skill.skill_id,
			name: skill.name,
			description: skill.description,
			triggers: skill.triggers,
			when_to_use: skill.when_to_use,
			recommended_tools: skill.recommended_tools,
			prompt_mode: skill.prompt_mode,
			source_id: skill.source_id,
			installed: true,
			enabled: true,
			pinned: skill.skill_id === "android-local-runtime",
			disabled_until: null,
			metadata: {
				runtime: "android-local",
				source_id: skill.source_id,
				installed: true,
			},
		}));
	}

	private localSelectedSkills(message: string, hints: string[] = []) {
		const normalized = message.toLowerCase();
		const hinted = new Set(hints);
		const selected = this.localSkillCatalogItems().filter((skill) => {
			if (
				hinted.has(String(skill.skill_id)) ||
				hinted.has(String(skill.name))
			) {
				return true;
			}
			return stringArray(skill.triggers).some((trigger) =>
				normalized.includes(trigger.toLowerCase()),
			);
		});
		return selected.length
			? selected
			: this.localSkillCatalogItems().slice(0, 1);
	}

	private localContextEvidenceRecord(
		input: { message?: unknown; thread_id?: unknown; turn_id?: unknown } = {},
	) {
		const timestamp = nowIso();
		const summary = stringValue(input.message).trim();
		const tokenCounting = {
			backend: "estimated",
			tokenizer_id: null,
			estimated: true,
		};
		return {
			evidence_id: this.nextId("audit", "local-context-evidence"),
			thread_id: nullableString(input.thread_id),
			turn_id: nullableString(input.turn_id),
			user_id: LOCAL_USER_ID,
			source_kind: "context_explain",
			created_at: timestamp,
			selected_memories: [],
			excluded_memories: [],
			compaction_summary:
				summary || "Android local runtime has no remote context evidence yet.",
			drift_report: null,
			artifact_refs: [],
			token_counting: tokenCounting,
			token_counting_backend: tokenCounting.backend,
			tokenizer_id: tokenCounting.tokenizer_id,
			estimated: tokenCounting.estimated,
			risk_flags: [],
			metadata: { runtime: "android-local" },
		};
	}

	private handleLocalAgentMemory(
		method: string,
		subresource?: string,
		third?: string,
		limit = 50,
	): Response {
		if (subresource === "curator" && third === "policy" && method === "GET") {
			return jsonResponse({
				enabled: true,
				auto_promote_on_merge: true,
				branch_local_only_until_merge: true,
				conflict_strategy: "needs_review",
			});
		}
		if (
			subresource === "curator" &&
			third === "evaluate" &&
			method === "POST"
		) {
			return jsonResponse({
				decision: {
					status: "skipped",
					reason: "Android local runtime keeps memory curation local.",
				},
			});
		}
		if (
			subresource === "curator" &&
			third === "decisions" &&
			method === "GET"
		) {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		if (subresource && third === "usage" && method === "GET") {
			return jsonResponse({ memory_id: subresource, usage: [], count: 0 });
		}
		return errorResponse(404, "Unsupported local agent memory route.");
	}

	private handleLocalAgentDelegation(
		method: string,
		subresource?: string,
		limit = 50,
		init?: RequestInit,
	): Response {
		const policy = {
			enabled: false,
			enforce: false,
			max_parallel_runs: 1,
			default_off_legacy_safe: true,
		};
		if (subresource === "policy" && method === "GET")
			return jsonResponse(policy);
		if (subresource === "plan" && method === "POST") {
			const body = parseJsonBody(init) as { message?: string };
			return jsonResponse({
				policy,
				plan: {
					tasks: [],
					message: body.message ?? "",
					reason: "Agent Team delegation is disabled in Android.",
				},
			});
		}
		if (subresource === "runs" && method === "GET") {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		return errorResponse(404, "Unsupported local agent delegation route.");
	}

	private handleLocalAgentModelRouter(
		method: string,
		subresource?: string,
		limit = 50,
		init?: RequestInit,
	): Response {
		const policy = {
			enabled: true,
			mode: "local",
			default_model:
				this.state.adminConfig.models.default_model || DEFAULT_MODEL_ID,
			helper_model: this.state.adminConfig.models.helper_model ?? null,
			role_models: this.localRolePolicy().role_models,
		};
		if (subresource === "policy" && method === "GET")
			return jsonResponse(policy);
		if (subresource === "route" && method === "POST") {
			const body = parseJsonBody(init) as { role?: string };
			return jsonResponse({
				decision: {
					model: policy.default_model,
					role: body.role ?? "planner",
					reason: "Android local runtime uses the locally selected model.",
				},
			});
		}
		if (subresource === "decisions" && method === "GET") {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		return errorResponse(404, "Unsupported local agent model router route.");
	}

	private handleLocalAgentContext(
		method: string,
		subresource?: string,
		limit = 50,
		init?: RequestInit,
	): Response {
		if (subresource === "policy" && method === "GET") {
			return jsonResponse({
				enabled: true,
				artifactize_long_observations: false,
				role_views_enabled: true,
				tokenizer_mode: "estimated",
				artifact_min_chars: 4000,
				default_off_legacy_safe: false,
			});
		}
		if (subresource === "preview" && method === "POST") {
			const body = parseJsonBody(init) as {
				assembled_context?: string | null;
				materialize_artifacts?: boolean | null;
				prompt_mode?: string;
				role?: string;
				state?: Record<string, unknown>;
			};
			const assembledContext = stringValue(body.assembled_context ?? "");
			const promptChars = assembledContext.length;
			const budgetState = isRecord(body.state?.context_budget)
				? body.state.context_budget
				: {};
			const promptLimit = Number(budgetState.prompt_token_limit ?? 1200);
			const charsPerToken = Number(budgetState.chars_per_token ?? 4) || 4;
			const promptTokens = Math.ceil(promptChars / charsPerToken);
			const maxPromptChars = promptLimit * charsPerToken;
			const overBudgetChars = Math.max(0, promptChars - maxPromptChars);
			return jsonResponse({
				decision: {
					role: body.role ?? "planner",
					prompt_mode: body.prompt_mode ?? "execute",
					token_count: promptTokens,
					budget: {
						prompt_chars: promptChars,
						prompt_tokens: promptTokens,
						prompt_token_limit: promptLimit,
						over_budget_chars: overBudgetChars,
						status: overBudgetChars > 0 ? "over" : "ok",
					},
					compression_plan: {
						required: overBudgetChars > 0,
						estimated_saved_chars: overBudgetChars,
						actions: overBudgetChars > 0 ? ["summarize_rolling_context"] : [],
					},
					materialized_artifacts: body.materialize_artifacts ? [] : [],
					selected_memories: [],
					excluded_memories: [],
					risk_flags: [],
					runtime: "android-local",
				},
			});
		}
		if (subresource === "decisions" && method === "GET") {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		if (subresource === "artifacts" && method === "GET") {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		if (subresource === "evidence" && method === "GET") {
			return jsonResponse({
				items: [],
				count: 0,
				filters: {},
				limit,
				backend: "android-local",
				available: true,
				error: null,
			});
		}
		if (subresource === "explain" && method === "POST") {
			const body = parseJsonBody(init) as {
				message?: string | null;
				thread_id?: string | null;
				turn_id?: string | null;
			};
			const evidence = this.localContextEvidenceRecord(body);
			return jsonResponse({
				evidence,
				item: evidence,
				answerability: null,
				backend: "android-local",
				available: true,
			});
		}
		return errorResponse(404, "Unsupported local agent context route.");
	}

	private handleLocalAgentTaskLedger(
		method: string,
		subresource?: string,
		limit = 50,
		init?: RequestInit,
	): Response {
		const policy = {
			enabled: true,
			artifact_synthesis_enabled: false,
			critic_gate_enabled: false,
			critic_gate_enforce: false,
			default_off_legacy_safe: false,
		};
		if (subresource === "policy" && method === "GET")
			return jsonResponse(policy);
		if (subresource === "plan" && method === "POST") {
			const body = parseJsonBody(init) as { message?: string };
			const task = {
				task_id: "android-local-task-1",
				role: "executor",
				status: "planned",
				title:
					stringValue(body.message).trim().slice(0, 80) || "Android local task",
				dependencies: [],
				retry_count: 0,
				runtime: "android-local",
			};
			return jsonResponse({
				policy,
				ledger: {
					tasks: [task],
					message: body.message ?? "",
					runtime: "android-local",
				},
				artifacts: [],
				critic_gate_result: null,
				synthesis_result: null,
			});
		}
		if (subresource === "runs" && method === "GET") {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		return errorResponse(404, "Unsupported local agent task ledger route.");
	}

	private localMemoryRecords() {
		const forgottenMemoryIds = new Set(this.state.forgottenMemoryIds ?? []);
		return Object.values(this.state.threads)
			.map((thread) => {
				const threadRecord = thread as unknown as JsonRecord;
				const createdAt = stringValue(threadRecord.created_at) || nowIso();
				const updatedAt = stringValue(threadRecord.updated_at) || createdAt;
				const memoryId = `local-memory-${thread.thread_id}`;
				const messages = (thread.messages ?? []) as Array<
					Record<string, unknown>
				>;
				const lastMessage = [...messages]
					.reverse()
					.find((message) => stringValue(message.content).trim());
				const content =
					stringValue(lastMessage?.content).trim() ||
					thread.assistant_message ||
					"Local Android conversation state.";
				return {
					memory_id: memoryId,
					kind: "conversation",
					scope: "thread",
					visibility: "private",
					status: "active",
					namespace: ["android-local", "conversation"],
					content,
					summary: content.slice(0, 180),
					tags: ["android-local"],
					evidence_refs: [thread.thread_id],
					source_thread_id: thread.thread_id,
					source_branch_id: thread.branch_meta?.branch_id ?? null,
					root_thread_id: thread.root_thread_id,
					user_id: LOCAL_USER_ID,
					confidence: 0.8,
					importance: 0.5,
					promoted_to_main: thread.thread_id === thread.root_thread_id,
					fingerprint: thread.thread_id,
					semantic_key: thread.thread_id,
					embedding_status: "not_required",
					embedding_model_id: null,
					embedding_updated_at: null,
					created_at: createdAt,
					updated_at: updatedAt,
					deleted_at: null,
					payload_redacted: false,
				};
			})
			.filter((record) => !forgottenMemoryIds.has(record.memory_id));
	}

	private localTrajectoryList(searchParams: URLSearchParams) {
		const limit = searchParamNumber(searchParams, "limit", 50);
		const offset = searchParamNumber(searchParams, "offset", 0);
		const items = Object.values(this.state.threads)
			.map((thread) => this.localTrajectorySummary(thread))
			.sort((left, right) =>
				String(right.created_at).localeCompare(String(left.created_at)),
			)
			.slice(offset, offset + limit);
		return {
			items,
			count: items.length,
			filters: Object.fromEntries(searchParams.entries()),
			limit,
			offset,
		};
	}

	private localTrajectorySummary(thread: ThreadStateResponse) {
		const threadRecord = thread as unknown as JsonRecord;
		const messages = (thread.messages ?? []) as Array<Record<string, unknown>>;
		const humanMessages = messages.filter(
			(message) => message.type === "human",
		);
		const aiMessages = messages.filter((message) => message.type === "ai");
		const toolMessages = messages.filter((message) => message.type === "tool");
		const userMessage = stringValue(humanMessages.at(-1)?.content);
		const answer = stringValue(
			aiMessages.at(-1)?.content || thread.assistant_message,
		);
		const inputTokens = Math.ceil(userMessage.length / 4);
		const outputTokens = Math.ceil(answer.length / 4);
		const createdAt =
			stringValue(threadRecord.updated_at) ||
			stringValue(threadRecord.created_at) ||
			nowIso();
		const title = stringValue(threadRecord.title);
		return {
			id: `local-turn-${thread.thread_id}`,
			schema_version: 1,
			kind: "chat_turn",
			status: "succeeded",
			thread_id: thread.thread_id,
			root_thread_id: thread.root_thread_id,
			request_id: thread.trace?.last_run_id ?? null,
			trace_id: thread.trace?.last_run_id ?? null,
			root_span_id: null,
			environment: "android",
			deployment: "local",
			app_version: null,
			parent_thread_id: thread.branch_meta?.parent_thread_id ?? null,
			branch_id: thread.branch_meta?.branch_id ?? null,
			branch_role: thread.branch_meta?.branch_role ?? null,
			scene: "android-local",
			turn_index: messages.length,
			task_brief: title || null,
			user_message: userMessage,
			answer,
			selected_model: thread.selected_model,
			selected_thinking_mode: thread.selected_thinking_mode,
			error: null,
			started_at: createdAt,
			finished_at: createdAt,
			created_at: createdAt,
			metrics: {
				latency_ms: 0,
				tool_calls: toolMessages.length,
				llm_calls: aiMessages.length,
				input_tokens: inputTokens,
				output_tokens: outputTokens,
				total_tokens: inputTokens + outputTokens,
				cache_hits: 0,
				fallback_uses: 0,
				parallel_tool_calls: 0,
			},
			plan_meta: { runtime: "android-local" },
			latency_ms: 0,
			tool_calls: toolMessages.length,
			llm_calls: aiMessages.length,
			cache_hits: 0,
			fallback_uses: 0,
		};
	}

	private localTrajectoryDetail(turnId: string) {
		const thread = Object.values(this.state.threads).find(
			(item) => `local-turn-${item.thread_id}` === turnId,
		);
		if (!thread) return null;
		const summary = this.localTrajectorySummary(thread);
		const toolMessages = (thread.messages ?? []).filter(
			(message) => message.type === "tool",
		);
		return {
			...summary,
			user_id_hash: "android-local",
			plan: null,
			reflection: null,
			trajectory: toolMessages.map((message) => ({
				tool: stringValue(message.name) || "tool",
				args: {},
				observation: stringValue(message.content),
				duration_ms: 0,
				error:
					message.status === "failed" ? stringValue(message.content) : null,
				cache_hit: false,
				fallback_used: false,
				fallback_group: null,
				parallel_batch_size: null,
				runtime: { runtime: "android-local" },
				observation_truncated: false,
			})),
		};
	}

	private localTrajectoryStats() {
		const items = Object.values(this.state.threads).map((thread) =>
			this.localTrajectorySummary(thread),
		);
		const totalToolCalls = items.reduce(
			(sum, item) => sum + item.tool_calls,
			0,
		);
		const totalLlmCalls = items.reduce((sum, item) => sum + item.llm_calls, 0);
		const overview = {
			key: "android-local",
			turn_count: items.length,
			step_count: totalToolCalls,
			avg_latency_ms: 0,
			avg_duration_ms: 0,
			cache_hit_steps: 0,
			fallback_steps: 0,
			succeeded_count: items.length,
			non_succeeded_count: 0,
			total_tool_calls: totalToolCalls,
			total_llm_calls: totalLlmCalls,
			total_cache_hits: 0,
			total_fallback_uses: 0,
			max_latency_ms: 0,
		};
		return {
			overview,
			by_status: [{ ...overview, key: "succeeded" }],
			by_scene: [{ ...overview, key: "android-local" }],
			by_branch_role: [],
			by_model: [],
			by_day: [],
			by_tool: this.state.adminConfig.tools.tools.map((tool) => ({
				key: tool.name,
				turn_count: items.length,
				step_count: 0,
				total_tool_calls: 0,
			})),
		};
	}

	private localObservabilityOverview(searchParams: URLSearchParams) {
		return {
			generated_at: nowIso(),
			filters: Object.fromEntries(searchParams.entries()),
			runtime: {
				status: "ready",
				ready: true,
				app_version: null,
				environment: "android",
				deployment: "local",
				active_connections: 1,
				checks: [
					{
						name: "android-local-runtime",
						ready: true,
						detail: "In-app runtime is serving local endpoints.",
					},
				],
			},
			trajectory_available: true,
			trajectory_error: null,
			stats: this.localTrajectoryStats(),
		};
	}

	private localTrajectoryReplay(detail: JsonRecord, model?: string | null) {
		const modelUsed =
			nullableString(model) ||
			this.state.adminConfig.models.default_model ||
			DEFAULT_MODEL_ID;
		return {
			source_turn_id: detail.id,
			model_used: modelUsed,
			replay_case: {
				id: `${detail.id}-replay`,
				input: { message: detail.user_message ?? "" },
				expected: {},
				tags: ["android-local"],
				scene: "android-local",
				skill_hints: [],
				setup: [],
				judge: {},
				origin: { source_turn_id: detail.id },
			},
			replay_case_jsonl: "",
			replay_result: {
				case_id: `${detail.id}-replay`,
				passed: true,
				answer: stringValue(detail.answer),
				verdicts: [],
				trajectory: [],
				metrics: {},
				error: null,
				tags: ["android-local"],
			},
			comparison: {
				case_id: `${detail.id}-replay`,
				trajectory_id: detail.id,
				source_status: detail.status,
				source_failed: false,
				replay_passed: true,
				replay_error: null,
				source_tools: [],
				replay_tools: [],
				tool_path_changed: false,
				source_tool_calls: Number(detail.tool_calls ?? 0),
				replay_tool_calls: 0,
				source_latency_ms: Number(detail.latency_ms ?? 0),
				replay_latency_ms: 0,
				source_fallback_uses: Number(detail.fallback_uses ?? 0),
				replay_fallback_uses: 0,
				source_cache_hits: Number(detail.cache_hits ?? 0),
				source_answer_preview: stringValue(detail.answer).slice(0, 200),
				replay_answer_preview: stringValue(detail.answer).slice(0, 200),
			},
		};
	}

	private localTrajectoryPromotion(detail: JsonRecord) {
		const datasetRecord = {
			id: `${detail.id}-android-local-case`,
			input: { message: detail.user_message ?? "" },
			expected: { answer_substring: stringValue(detail.answer).slice(0, 120) },
			tags: ["android-local"],
			scene: "android-local",
			skill_hints: [],
			setup: [],
			judge: {},
			origin: { source_turn_id: detail.id },
		};
		return {
			source_turn_id: detail.id,
			case_id: datasetRecord.id,
			dataset_record: datasetRecord,
			jsonl: JSON.stringify(datasetRecord),
		};
	}

	private adminConfigResponse(): FocusAgentAdminConfig {
		const config = clone(this.state.adminConfig);
		config.models.providers = config.models.providers.map((provider) => ({
			...provider,
			api_key_configured: Boolean(
				this.modelSecrets[provider.id]?.apiKey?.trim(),
			),
			base_url_configured: Boolean(
				normalizedUrl(provider.base_url_default) || provider.base_url_env,
			),
		}));
		return config;
	}

	private providerMatchesModelPrefix(
		provider: FocusAgentAdminConfig["models"]["providers"][number],
		modelProviderPrefix: string,
	): boolean {
		const normalizedPrefix = modelProviderPrefix.trim().toLowerCase();
		if (!normalizedPrefix) return false;
		return (
			provider.id.toLowerCase() === normalizedPrefix ||
			provider.aliases.some(
				(alias) => alias.trim().toLowerCase() === normalizedPrefix,
			)
		);
	}

	private providerConfigForModel(selectedModel: string): {
		model: string;
		provider: FocusAgentAdminConfig["models"]["providers"][number] | null;
	} | null {
		const model = selectedModel.trim() || DEFAULT_MODEL_ID;
		const providerSeparatorIndex = model.indexOf(":");
		if (
			providerSeparatorIndex > 0 &&
			providerSeparatorIndex < model.length - 1
		) {
			const providerPrefix = model.slice(0, providerSeparatorIndex);
			const modelName = model.slice(providerSeparatorIndex + 1);
			const provider =
				this.state.adminConfig.models.providers.find((item) =>
					this.providerMatchesModelPrefix(item, providerPrefix),
				) ?? null;
			return { model: modelName, provider };
		}
		if (providerSeparatorIndex > 0) return null;
		const [provider] = this.state.adminConfig.models.providers;
		return provider ? { model, provider } : null;
	}

	private modelProvider(
		selectedModel: string,
	): ResolvedLocalModelProvider | null {
		const resolved = this.providerConfigForModel(selectedModel);
		if (!resolved?.provider) return null;
		const provider = resolved.provider;
		const apiKey = this.modelSecrets[provider.id]?.apiKey?.trim() ?? "";
		if (!apiKey) return null;
		return {
			model: resolved.model,
			provider: {
				id: provider.id,
				label: provider.label ?? provider.id,
				baseUrl:
					normalizedUrl(provider.base_url_default) || DEFAULT_PROVIDER_BASE_URL,
				apiKey,
			},
		};
	}

	private modelProviderLabel(selectedModel: string): string {
		const resolved = this.providerConfigForModel(selectedModel);
		const [fallbackProvider] = this.state.adminConfig.models.providers;
		const provider = resolved?.provider ?? fallbackProvider;
		return provider?.label ?? provider?.id ?? "DeepSeek";
	}

	private chatMessages(
		thread: ThreadStateResponse,
		webSearchResult?: LocalWebSearchResult | null,
		webFetchResult?: LocalWebFetchResult | null,
		localToolExecutions: LocalToolExecution[] = [],
	): ChatCompletionMessage[] {
		const history = this.threadMessagesForProvider(thread).slice(-24);
		const toolContext: ChatCompletionMessage[] = [];
		if (webSearchResult) {
			toolContext.push({
				role: "system",
				content: [
					"The Android local runtime already executed web_search for this turn.",
					"Use these search results as current external evidence and cite URLs when useful.",
					JSON.stringify(webSearchResult),
				].join("\n"),
			});
		}
		if (webFetchResult) {
			toolContext.push({
				role: "system",
				content: [
					"The Android local runtime already executed web_fetch for this turn.",
					"Use the fetched page content as external evidence and cite the URL when useful.",
					JSON.stringify(webFetchResult),
				].join("\n"),
			});
		}
		for (const execution of localToolExecutions) {
			toolContext.push({
				role: "system",
				content: [
					`The Android local runtime already executed ${execution.name} for this turn.`,
					"Use this app-local tool output when answering.",
					JSON.stringify(execution.output),
				].join("\n"),
			});
		}
		return [
			{
				role: "system",
				content:
					"You are Focus Agent running inside an Android app-local runtime. Keep answers concise, useful, and do not claim access to a Focus Agent backend.",
			},
			...history,
			...toolContext,
		];
	}

	private localAppToolPlan(
		thread: ThreadStateResponse,
		message: string,
	): Array<{ name: string; args: Record<string, unknown> }> {
		const normalized = message.toLowerCase();
		const tools: Array<{ name: string; args: Record<string, unknown> }> = [];
		const push = (name: string, args: Record<string, unknown>) => {
			if (this.localToolEnabled(name)) tools.push({ name, args });
		};
		if (
			containsAny(normalized, [
				"save artifact",
				"write artifact",
				"write_text_artifact",
				"保存为产物",
				"写入产物",
				"保存产物",
			])
		) {
			const title =
				quotedText(message) ??
				afterCue(message, ["title:", "标题：", "标题:"]) ??
				message.slice(0, 48);
			const body =
				afterCue(message, ["body:", "content:", "正文：", "内容："]) ?? message;
			push("write_text_artifact", { title, body });
		}
		if (
			containsAny(normalized, [
				"list artifacts",
				"artifact list",
				"artifact_list",
				"列出产物",
				"产物列表",
			])
		) {
			push("artifact_list", {});
		}
		if (
			containsAny(normalized, [
				"read artifact",
				"artifact_read",
				"读取产物",
				"打开产物",
			])
		) {
			push("artifact_read", {
				artifact_id: this.localArtifactIdFromMessage(message),
			});
		}
		if (
			containsAny(normalized, [
				"update artifact",
				"append artifact",
				"artifact_update",
				"更新产物",
				"追加产物",
			])
		) {
			push("artifact_update", {
				artifact_id: this.localArtifactIdFromMessage(message),
				body:
					afterCue(message, ["body:", "content:", "追加：", "内容："]) ??
					message,
				mode: containsAny(normalized, ["append", "追加"])
					? "append"
					: "replace",
			});
		}
		if (
			containsAny(normalized, [
				"remember",
				"save memory",
				"memory_save",
				"记住",
				"保存记忆",
			])
		) {
			push("memory_save", {
				content:
					afterCue(message, [
						"remember",
						"记住",
						"保存记忆",
						"content:",
						"内容：",
					]) ?? message,
				kind: "user_preference",
				scope: "user",
				user_id: LOCAL_USER_ID,
			});
		}
		if (
			containsAny(normalized, [
				"search memory",
				"memory_search",
				"搜索记忆",
				"查找记忆",
				"记忆里",
			])
		) {
			push("memory_search", {
				query:
					afterCue(message, [
						"search memory",
						"memory_search",
						"搜索记忆",
						"查找记忆",
					]) ?? message,
				user_id: LOCAL_USER_ID,
				root_thread_id: thread.root_thread_id,
			});
		}
		if (
			containsAny(normalized, [
				"forget memory",
				"memory_forget",
				"忘记",
				"遗忘记忆",
			])
		) {
			push("memory_forget", {
				memory_id: this.localMemoryIdFromMessage(message),
				user_id: LOCAL_USER_ID,
			});
		}
		if (
			containsAny(normalized, [
				"conversation summary",
				"conversation_summary",
				"summarize conversation",
				"会话摘要",
				"总结当前会话",
			])
		) {
			push("conversation_summary", { thread_id: thread.thread_id });
		}
		if (
			containsAny(normalized, [
				"list skills",
				"skills_list",
				"技能列表",
				"列出技能",
			])
		) {
			push("skills_list", {});
		}
		if (
			containsAny(normalized, ["skill sources", "skill_sources", "技能来源"])
		) {
			push("skill_sources", {});
		}
		if (
			containsAny(normalized, [
				"search skills",
				"skills_search",
				"搜索技能",
				"查找技能",
			])
		) {
			push("skills_search", {
				query:
					afterCue(message, ["search skills", "skills_search", "搜索技能"]) ??
					message,
				limit: 5,
			});
		}
		if (containsAny(normalized, ["skill_view", "view skill", "查看技能"])) {
			push("skill_view", {
				name:
					quotedText(message) ??
					afterCue(message, ["skill_view", "view skill", "查看技能"]) ??
					ANDROID_LOCAL_SKILLS[0]?.skill_id,
			});
		}
		if (
			containsAny(normalized, ["skill_install", "install skill", "安装技能"])
		) {
			push("skill_install", {
				skill_id:
					quotedText(message) ??
					afterCue(message, ["skill_install", "install skill", "安装技能"]) ??
					ANDROID_LOCAL_SKILLS[0]?.skill_id,
			});
		}
		if (
			containsAny(normalized, [
				"skills_refresh_index",
				"refresh skills",
				"刷新技能索引",
			])
		) {
			push("skills_refresh_index", {});
		}
		if (
			containsAny(normalized, [
				"list_files",
				"list files",
				"列出文件",
				"文件列表",
			])
		) {
			push("list_files", { path: ".", pattern: "**/*" });
		}
		if (
			containsAny(normalized, [
				"read_file",
				"read file",
				"读取文件",
				"查看文件",
			])
		) {
			push("read_file", {
				path: this.localWorkspacePathFromMessage(message) ?? "README.md",
			});
		}
		if (
			containsAny(normalized, [
				"search_code",
				"search code",
				"搜索代码",
				"代码搜索",
			])
		) {
			const rawQuery =
				afterCue(message, ["search_code", "search code", "搜索代码"]) ??
				"android";
			push("search_code", {
				query: rawQuery.split(/[，,。;\s]+/u).find(Boolean) ?? "android",
				path: ".",
				literal: true,
			});
		}
		if (
			containsAny(normalized, [
				"codebase_stats",
				"codebase stats",
				"代码库统计",
				"工作区统计",
			])
		) {
			push("codebase_stats", { path: "." });
		}
		if (
			containsAny(normalized, [
				"apply_patch",
				"apply patch",
				"应用补丁",
				"打补丁",
			])
		) {
			push("apply_patch", {
				patch: this.localPatchFromMessage(message),
			});
		}
		if (
			containsAny(normalized, [
				"run_workspace_command",
				"workspace command",
				"运行工作区命令",
				"执行命令",
			])
		) {
			push("run_workspace_command", {
				command: this.localCommandFromMessage(message),
				cwd: ".",
			});
		}
		if (containsAny(normalized, ["git_status", "git status", "git 状态"])) {
			push("git_status", {});
		}
		if (containsAny(normalized, ["git_diff", "git diff", "git 差异"])) {
			push("git_diff", {});
		}
		if (containsAny(normalized, ["git_log", "git log", "git 日志"])) {
			push("git_log", { limit: 5 });
		}
		return tools.slice(0, 8);
	}

	private localArtifactIdFromMessage(message: string): string | null {
		const artifactId = message.match(/[\p{Letter}\p{Number}_-]+\.md/iu)?.[0];
		return artifactId ?? this.state.artifacts?.[0]?.artifact_id ?? null;
	}

	private localMemoryIdFromMessage(message: string): string | null {
		const memoryId = message.match(/local-memory-\d+/i)?.[0];
		return (
			memoryId ??
			this.state.memories?.find((item) => !item.deleted_at)?.memory_id ??
			null
		);
	}

	private localArtifactsForThread(
		thread: ThreadStateResponse,
	): LocalArtifact[] {
		return (this.state.artifacts ?? [])
			.filter(
				(artifact) =>
					artifact.root_thread_id === thread.root_thread_id ||
					artifact.thread_id === thread.thread_id,
			)
			.sort((left, right) => right.updated_at.localeCompare(left.updated_at));
	}

	private localSkillPayload(skill: LocalSkill): Record<string, unknown> {
		return {
			skill_id: skill.skill_id,
			name: skill.name,
			description: skill.description,
			triggers: skill.triggers,
			when_to_use: skill.when_to_use,
			recommended_tools: skill.recommended_tools,
			prompt_mode: skill.prompt_mode,
			source_id: skill.source_id,
			installed: true,
		};
	}

	private workspaceFiles(): Record<string, string> {
		this.state.workspaceFiles ??= defaultWorkspaceFiles();
		return this.state.workspaceFiles;
	}

	private workspaceBaseFiles(): Record<string, string> {
		this.state.workspaceBaseFiles ??= clone(this.workspaceFiles());
		return this.state.workspaceBaseFiles;
	}

	private normalizeWorkspacePath(value: unknown): string | null {
		const raw = stringValue(value).trim() || ".";
		if (raw.startsWith("/") || raw.includes("\0")) return null;
		const parts: string[] = [];
		for (const part of raw.split("/")) {
			if (!part || part === ".") continue;
			if (part === "..") return null;
			parts.push(part);
		}
		return parts.join("/") || ".";
	}

	private localWorkspacePathFromMessage(message: string): string | null {
		return (
			message.match(/[\p{Letter}\p{Number}_./-]+\.[a-z0-9]+/iu)?.[0] ?? null
		);
	}

	private localPatchFromMessage(message: string): string {
		const fenced = message.match(/```(?:diff|patch)?\s*([\s\S]*?)```/i)?.[1];
		if (fenced?.includes("diff --git")) return fenced.trim();
		const target = this.localWorkspacePathFromMessage(message) ?? "README.md";
		const normalizedTarget = this.normalizeWorkspacePath(target) ?? "README.md";
		return [
			`diff --git a/${normalizedTarget} b/${normalizedTarget}`,
			`--- a/${normalizedTarget}`,
			`+++ b/${normalizedTarget}`,
			"@@ -1,3 +1,4 @@",
			" # Focus Agent Android Local Workspace",
			" ",
			"+Patched from Android local runtime.",
			" This is an app-local virtual workspace used when Focus Agent runs on Android without a backend.",
			"",
		].join("\n");
	}

	private localCommandFromMessage(message: string): string[] {
		const fenced = message.match(/`([^`]+)`/)?.[1];
		const raw =
			fenced ??
			afterCue(message, [
				"run_workspace_command",
				"workspace command",
				"运行工作区命令",
				"执行命令",
			]) ??
			"ls";
		return raw.trim().split(/\s+/).filter(Boolean).slice(0, 8);
	}

	private workspaceFileEntries(pathValue: unknown = ".") {
		const path = this.normalizeWorkspacePath(pathValue) ?? ".";
		const prefix = path === "." ? "" : `${path.replace(/\/$/, "")}/`;
		return Object.entries(this.workspaceFiles())
			.filter(
				([filePath]) =>
					path === "." || filePath === path || filePath.startsWith(prefix),
			)
			.sort(([left], [right]) => left.localeCompare(right));
	}

	private languageForPath(path: string): string {
		if (path.endsWith(".ts") || path.endsWith(".tsx")) return "TypeScript";
		if (path.endsWith(".js") || path.endsWith(".jsx")) return "JavaScript";
		if (path.endsWith(".py")) return "Python";
		if (path.endsWith(".md")) return "Markdown";
		if (path.endsWith(".json")) return "JSON";
		return "Text";
	}

	private fileDiff(path: string, before = "", after = ""): string {
		if (before === after) return "";
		const beforeLines = before.split("\n");
		const afterLines = after.split("\n");
		const lines = [
			`diff --git a/${path} b/${path}`,
			before ? `--- a/${path}` : "--- /dev/null",
			after ? `+++ b/${path}` : "+++ /dev/null",
			`@@ -1,${Math.max(1, beforeLines.length)} +1,${Math.max(1, afterLines.length)} @@`,
			...beforeLines
				.filter((line, index) => line !== afterLines[index])
				.map((line) => `-${line}`),
			...afterLines
				.filter((line, index) => line !== beforeLines[index])
				.map((line) => `+${line}`),
		];
		return lines.join("\n");
	}

	private workspaceDiff(pathspec?: unknown): string {
		const normalizedPathspec = this.normalizeWorkspacePath(pathspec ?? ".");
		const baseFiles = this.workspaceBaseFiles();
		const currentFiles = this.workspaceFiles();
		const allPaths = [
			...new Set([...Object.keys(baseFiles), ...Object.keys(currentFiles)]),
		].sort();
		return allPaths
			.filter(
				(path) =>
					!normalizedPathspec ||
					normalizedPathspec === "." ||
					path === normalizedPathspec ||
					path.startsWith(`${normalizedPathspec}/`),
			)
			.map((path) =>
				this.fileDiff(path, baseFiles[path] ?? "", currentFiles[path] ?? ""),
			)
			.filter(Boolean)
			.join("\n");
	}

	private workspaceStatusEntries(): string[] {
		const baseFiles = this.workspaceBaseFiles();
		const currentFiles = this.workspaceFiles();
		const allPaths = [
			...new Set([...Object.keys(baseFiles), ...Object.keys(currentFiles)]),
		].sort();
		return allPaths.flatMap((path) => {
			if (!(path in baseFiles)) return [`?? ${path}`];
			if (!(path in currentFiles)) return [` D ${path}`];
			if (baseFiles[path] !== currentFiles[path]) return [` M ${path}`];
			return [];
		});
	}

	private applyPatchToWorkspace(patch: string): string[] {
		if (patch.length > 20000)
			throw new Error("patch exceeds Android local limit.");
		if (
			/new file mode 120000|new file mode 160000|Subproject commit/i.test(patch)
		) {
			throw new Error("Symlink and submodule patches are not supported.");
		}
		const changedFiles: string[] = [];
		const fileSections = patch.split(/^diff --git /m).filter(Boolean);
		for (const rawSection of fileSections) {
			const section = `diff --git ${rawSection}`;
			const path = this.normalizeWorkspacePath(
				section.match(/^\+\+\+ b\/(.+)$/m)?.[1],
			);
			if (!path || path === ".")
				throw new Error("Patch path must stay inside workspace root.");
			const original = this.workspaceFiles()[path] ?? "";
			const originalLines = original.split("\n");
			const outputLines: string[] = [];
			let cursor = 0;
			const hunkMatches = [
				...section.matchAll(/^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@.*$/gm),
			];
			if (hunkMatches.length === 0) continue;
			for (let hunkIndex = 0; hunkIndex < hunkMatches.length; hunkIndex += 1) {
				const match = hunkMatches[hunkIndex];
				const start = Math.max(0, Number(match[1]) - 1);
				outputLines.push(...originalLines.slice(cursor, start));
				cursor = start;
				const hunkStart = (match.index ?? 0) + match[0].length + 1;
				const hunkEnd = hunkMatches[hunkIndex + 1]?.index ?? section.length;
				const hunkLines = section.slice(hunkStart, hunkEnd).split(/\r?\n/);
				for (const line of hunkLines) {
					if (!line) continue;
					const marker = line[0];
					const text = line.slice(1);
					if (marker === " ") {
						outputLines.push(originalLines[cursor] ?? text);
						cursor += 1;
					} else if (marker === "-") {
						cursor += 1;
					} else if (marker === "+") {
						outputLines.push(text);
					}
				}
			}
			outputLines.push(...originalLines.slice(cursor));
			this.workspaceFiles()[path] =
				`${outputLines.join("\n").replace(/\n+$/u, "")}\n`;
			changedFiles.push(path);
		}
		return changedFiles;
	}

	private executeLocalAppTool(
		thread: ThreadStateResponse,
		name: string,
		args: Record<string, unknown>,
	): LocalToolExecution {
		const timestamp = nowIso();
		let output: unknown;
		let message = `${name} completed.`;
		if (name === "write_text_artifact") {
			const title = stringValue(args.title).trim() || "Android local artifact";
			const body = stringValue(args.body) || stringValue(args.content);
			const artifactId = slugifyArtifactTitle(title);
			const artifact: LocalArtifact = {
				artifact_id: artifactId,
				title,
				content: `# ${title}\n\n${body}\n`,
				content_type: "text/markdown",
				created_at: timestamp,
				updated_at: timestamp,
				root_thread_id: thread.root_thread_id,
				thread_id: thread.thread_id,
			};
			this.state.artifacts = [
				artifact,
				...(this.state.artifacts ?? []).filter(
					(item) => item.artifact_id !== artifactId,
				),
			];
			message = `artifact_saved:app-local/artifacts/${artifactId}`;
			output = {
				success: true,
				saved: true,
				artifact_id: artifactId,
				title,
				path: `app-local/artifacts/${artifactId}`,
				result: message,
			};
		} else if (name === "artifact_list") {
			const artifacts = this.localArtifactsForThread(thread).map(
				(artifact) => ({
					artifact_id: artifact.artifact_id,
					title: artifact.title,
					content_type: artifact.content_type,
					size: artifact.content.length,
					created_at: artifact.created_at,
					updated_at: artifact.updated_at,
					thread_id: artifact.thread_id,
					root_thread_id: artifact.root_thread_id,
				}),
			);
			output = { artifacts, count: artifacts.length };
			message = `${artifacts.length} local artifacts.`;
		} else if (name === "artifact_read") {
			const artifactId = nullableString(args.artifact_id);
			const artifact = this.localArtifactsForThread(thread).find(
				(item) => item.artifact_id === artifactId,
			);
			output = artifact
				? { success: true, ...artifact }
				: {
						success: false,
						error: "artifact_not_found",
						artifact_id: artifactId,
					};
			message = artifact ? artifact.title : "Artifact not found.";
		} else if (name === "artifact_update") {
			const artifactId = nullableString(args.artifact_id);
			const artifact = this.localArtifactsForThread(thread).find(
				(item) => item.artifact_id === artifactId,
			);
			const body = stringValue(args.body) || stringValue(args.content);
			const mode = stringValue(args.mode) === "append" ? "append" : "replace";
			if (artifact) {
				artifact.content =
					mode === "append"
						? `${artifact.content.trimEnd()}\n\n${body}\n`
						: body;
				artifact.updated_at = timestamp;
				output = {
					success: true,
					artifact_id: artifact.artifact_id,
					title: artifact.title,
					mode,
					updated_at: artifact.updated_at,
				};
				message = `artifact_updated:${artifact.artifact_id}`;
			} else {
				output = {
					success: false,
					error: "artifact_not_found",
					artifact_id: artifactId,
				};
				message = "Artifact not found.";
			}
		} else if (name === "memory_save") {
			const content = stringValue(args.content).trim();
			const scope =
				stringValue(args.scope) === "conversation" ||
				stringValue(args.scope) === "root_thread"
					? "root_thread"
					: "user";
			const memory: LocalMemory = {
				memory_id: this.nextId("memory", "local-memory"),
				content,
				kind: stringValue(args.kind) || "fact",
				scope,
				visibility: "shared",
				user_id: scope === "user" ? LOCAL_USER_ID : null,
				root_thread_id: scope === "root_thread" ? thread.root_thread_id : null,
				tags: stringArray(args.tags),
				created_at: timestamp,
				updated_at: timestamp,
				deleted_at: null,
			};
			this.state.memories = [memory, ...(this.state.memories ?? [])];
			output = {
				saved: true,
				action: "written",
				memory_id: memory.memory_id,
				scope: memory.scope,
				visibility: memory.visibility,
				namespace:
					memory.scope === "root_thread"
						? ["conversation", thread.root_thread_id, "main"]
						: ["user", LOCAL_USER_ID, "profile"],
			};
			message = `memory_saved:${memory.memory_id}`;
		} else if (name === "memory_search") {
			const queryWords = textWords(stringValue(args.query));
			const results = (this.state.memories ?? [])
				.filter((memory) => !memory.deleted_at)
				.map((memory) => {
					const memoryWords = new Set(textWords(memory.content));
					const overlap = queryWords.filter((word) =>
						memoryWords.has(word),
					).length;
					const score = queryWords.length ? overlap / queryWords.length : 1;
					return { memory, score };
				})
				.filter((item) => item.score > 0 || queryWords.length === 0)
				.sort((left, right) => right.score - left.score)
				.slice(0, Number(args.limit ?? 5))
				.map(({ memory, score }) => ({
					memory_id: memory.memory_id,
					content: memory.content,
					kind: memory.kind,
					scope: memory.scope,
					visibility: memory.visibility,
					score,
					updated_at: memory.updated_at,
				}));
			output = { results, count: results.length };
			message = `${results.length} local memories matched.`;
		} else if (name === "memory_forget") {
			const memoryId = nullableString(args.memory_id);
			const memory = (this.state.memories ?? []).find(
				(item) => item.memory_id === memoryId && !item.deleted_at,
			);
			if (memory) {
				memory.deleted_at = timestamp;
				memory.updated_at = timestamp;
			}
			this.state.forgottenMemoryIds = [
				...(this.state.forgottenMemoryIds ?? []),
				...(memoryId ? [memoryId] : []),
			];
			output = { deleted: Boolean(memory), memory_id: memoryId };
			message = memory ? `memory_deleted:${memoryId}` : "Memory not found.";
		} else if (name === "conversation_summary") {
			const recentMessages = thread.messages.slice(-8).map((item) => ({
				type: item.type,
				content: String(item.content ?? "").slice(0, 500),
				created_at: item.created_at,
			}));
			output = {
				thread_id: thread.thread_id,
				root_thread_id: thread.root_thread_id,
				rolling_summary: thread.rolling_summary ?? "",
				active_skill_ids: thread.active_skill_ids ?? [],
				recent_messages: recentMessages,
			};
			message = "conversation_summary completed.";
		} else if (name === "skills_list") {
			output = {
				success: true,
				skills: ANDROID_LOCAL_SKILLS.map((skill) =>
					this.localSkillPayload(skill),
				),
				count: ANDROID_LOCAL_SKILLS.length,
			};
			message = `${ANDROID_LOCAL_SKILLS.length} local skills.`;
		} else if (name === "skill_sources") {
			output = {
				success: true,
				sources: [
					{
						source_id: "android-local",
						label: "Android local built-ins",
						installed: true,
						count: ANDROID_LOCAL_SKILLS.length,
					},
				],
			};
			message = "skill_sources completed.";
		} else if (name === "skills_search") {
			const queryWords = textWords(stringValue(args.query));
			const limit = Number(args.limit ?? 5);
			const results = ANDROID_LOCAL_SKILLS.map((skill) => {
				const haystack = [
					skill.name,
					skill.description,
					...skill.triggers,
					...skill.when_to_use,
				].join(" ");
				const haystackWords = new Set(textWords(haystack));
				const score = queryWords.length
					? queryWords.filter((word) => haystackWords.has(word)).length /
						queryWords.length
					: 1;
				return { ...this.localSkillPayload(skill), score };
			})
				.filter((item) => item.score > 0 || queryWords.length === 0)
				.sort((left, right) => right.score - left.score)
				.slice(0, limit);
			output = { success: true, results, count: results.length };
			message = `${results.length} local skills matched.`;
		} else if (name === "skill_view") {
			const requested = stringValue(args.name) || stringValue(args.skill_id);
			const skill =
				ANDROID_LOCAL_SKILLS.find(
					(item) => item.skill_id === requested || item.name === requested,
				) ?? ANDROID_LOCAL_SKILLS[0];
			output = skill
				? {
						success: true,
						...this.localSkillPayload(skill),
						content: skill.content,
					}
				: { success: false, error: "skill_not_found", name: requested };
			message = skill ? skill.name : "Skill not found.";
		} else if (name === "skill_install") {
			const requested = stringValue(args.skill_id) || stringValue(args.name);
			const skill =
				ANDROID_LOCAL_SKILLS.find(
					(item) => item.skill_id === requested || item.name === requested,
				) ?? ANDROID_LOCAL_SKILLS[0];
			output = skill
				? {
						success: true,
						installed: true,
						...this.localSkillPayload(skill),
					}
				: { success: false, error: "skill_not_found", skill_id: requested };
			message = skill
				? `skill_installed:${skill.skill_id}`
				: "Skill not found.";
		} else if (name === "skills_refresh_index") {
			output = {
				success: true,
				refreshed: true,
				indexed_count: ANDROID_LOCAL_SKILLS.length,
				source_ids: ["android-local"],
			};
			message = `skills_index_refreshed:${ANDROID_LOCAL_SKILLS.length}`;
		} else if (name === "list_files") {
			const maxResults = Math.min(Number(args.max_results ?? 100), 500);
			const results = this.workspaceFileEntries(args.path)
				.map(([path]) => path)
				.slice(0, maxResults);
			output = {
				results,
				count: results.length,
				truncated: this.workspaceFileEntries(args.path).length > results.length,
				root: "app-local://workspace",
			};
			message = `${results.length} workspace files.`;
		} else if (name === "read_file") {
			const path = this.normalizeWorkspacePath(args.path);
			const content = path ? this.workspaceFiles()[path] : undefined;
			if (!path || content === undefined) {
				output = { success: false, error: "file_not_found", path };
				message = "File not found.";
			} else {
				const startLine = Math.max(1, Number(args.start_line ?? 1));
				const maxEndLine = Number(args.end_line ?? startLine + 200);
				const lines = content.split("\n");
				const endLine = Math.min(lines.length, maxEndLine);
				const rendered = lines
					.slice(startLine - 1, endLine)
					.map((line, index) => `${startLine + index} | ${line}`)
					.join("\n");
				output = {
					success: true,
					path,
					start_line: startLine,
					end_line: endLine,
					content: rendered,
				};
				message = path;
			}
		} else if (name === "search_code") {
			const query = stringValue(args.query);
			const literal = args.literal !== false;
			const maxResults = Math.min(Number(args.max_results ?? 20), 100);
			const matcher = literal
				? (line: string) => line.toLowerCase().includes(query.toLowerCase())
				: (line: string) => new RegExp(query, "i").test(line);
			const results = this.workspaceFileEntries(args.path)
				.flatMap(([path, content]) =>
					content.split("\n").flatMap((line, index, lines) => {
						if (!query || !matcher(line)) return [];
						return [
							{
								path,
								line_number: index + 1,
								line,
								context: lines
									.slice(Math.max(0, index - 2), index + 3)
									.join("\n"),
							},
						];
					}),
				)
				.slice(0, maxResults);
			output = {
				results,
				count: results.length,
				truncated: results.length === maxResults,
			};
			message = `${results.length} search results.`;
		} else if (name === "codebase_stats") {
			const entries = this.workspaceFileEntries(args.path);
			const breakdown = new Map<string, { files: number; bytes: number }>();
			for (const [path, content] of entries) {
				const language = this.languageForPath(path);
				const current = breakdown.get(language) ?? { files: 0, bytes: 0 };
				current.files += 1;
				current.bytes += content.length;
				breakdown.set(language, current);
			}
			output = {
				files_scanned: entries.length,
				total_bytes: entries.reduce(
					(total, [, content]) => total + content.length,
					0,
				),
				language_breakdown: [...breakdown.entries()].map(
					([language, stats]) => ({
						language,
						...stats,
					}),
				),
			};
			message = `${entries.length} workspace files scanned.`;
		} else if (name === "apply_patch") {
			try {
				const changedFiles = this.applyPatchToWorkspace(
					stringValue(args.patch),
				);
				output = { applied: true, changed_files: changedFiles };
				message = `patch_applied:${changedFiles.join(",")}`;
			} catch (error) {
				output = {
					applied: false,
					error: error instanceof Error ? error.message : String(error),
				};
				message = "Patch failed.";
			}
		} else if (name === "run_workspace_command") {
			const command = Array.isArray(args.command)
				? args.command.map(String)
				: stringValue(args.command).split(/\s+/).filter(Boolean);
			const [program, ...rest] = command;
			let stdout = "";
			let stderr = "";
			let exitCode = 0;
			if (!program) {
				exitCode = 2;
				stderr = "Missing command.";
			} else if (program === "pwd") {
				stdout = "app-local://workspace\n";
			} else if (program === "ls") {
				const target = rest.find((item) => !item.startsWith("-")) ?? ".";
				stdout = `${this.workspaceFileEntries(target)
					.map(([path]) => path)
					.join("\n")}\n`;
			} else if (program === "cat") {
				const path = this.normalizeWorkspacePath(rest[0]);
				stdout = path ? (this.workspaceFiles()[path] ?? "") : "";
				if (!stdout) {
					exitCode = 1;
					stderr = "File not found.";
				}
			} else if (program === "rg") {
				const query = rest.find((item) => !item.startsWith("-")) ?? "";
				const matches = this.workspaceFileEntries(".").flatMap(
					([path, content]) =>
						content
							.split("\n")
							.flatMap((line, index) =>
								line.toLowerCase().includes(query.toLowerCase())
									? [`${path}:${index + 1}:${line}`]
									: [],
							),
				);
				stdout = `${matches.join("\n")}\n`;
				exitCode = matches.length ? 0 : 1;
			} else if (program === "git" && rest[0] === "status") {
				stdout = `${this.workspaceStatusEntries().join("\n") || "clean"}\n`;
			} else if (program === "git" && rest[0] === "diff") {
				stdout = this.workspaceDiff(rest[1]) || "";
			} else {
				exitCode = 127;
				stderr =
					"Android local runtime supports only pwd, ls, cat, rg, git status, and git diff.";
			}
			output = {
				command,
				cwd: ".",
				exit_code: exitCode,
				stdout,
				stderr,
				truncated: false,
			};
			message = `command_exit:${exitCode}`;
		} else if (name === "git_status") {
			const entries = this.workspaceStatusEntries();
			output = {
				branch: "android-local",
				entries,
				clean: entries.length === 0,
				porcelain: entries.join("\n"),
			};
			message = entries.length ? `${entries.length} changed files.` : "clean";
		} else if (name === "git_diff") {
			const diff = this.workspaceDiff(args.pathspec);
			output = {
				diff,
				truncated: false,
			};
			message = diff ? "git_diff completed." : "No local diff.";
		} else if (name === "git_log") {
			const limit = Math.min(Number(args.limit ?? 10), 50);
			const commits = (this.state.gitCommits ?? defaultGitCommits())
				.slice(0, limit)
				.map((commit) => ({ ...commit }));
			output = { commits, count: commits.length };
			message = `${commits.length} commits.`;
		} else {
			output = { success: false, error: "unsupported_local_tool", name };
			message = `Unsupported local tool: ${name}`;
		}
		return { name, args, message, output };
	}

	private threadMessagesForProvider(
		thread: ThreadStateResponse,
	): ChatCompletionMessage[] {
		const messages: ChatCompletionMessage[] = [];
		for (const message of thread.messages) {
			const content = String(message.content ?? "").trim();
			if (!content) continue;
			const type = String(message.type ?? "");
			if (type === "human") {
				messages.push({ role: "user", content });
			} else if (type === "ai") {
				messages.push({ role: "assistant", content });
			}
		}
		return messages;
	}

	private async handleV1(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Promise<Response> {
		const [resource] = segments;
		if (resource === "auth") {
			return this.handleAuth(method, segments.slice(1), init);
		}
		if (resource === "models" && method === "GET") {
			return jsonResponse(this.modelsResponse());
		}
		if (resource === "branch-decisions") {
			return this.handleBranchDecisions(method, segments.slice(1));
		}
		if (resource === "conversations") {
			return this.handleConversations(method, segments.slice(1), init);
		}
		if (resource === "threads") {
			return this.handleThreads(method, segments.slice(1), searchParams, init);
		}
		if (resource === "branches") {
			return this.handleBranches(method, segments.slice(1), init);
		}
		if (resource === "agent") {
			return this.handleAgent(method, segments.slice(1), searchParams, init);
		}
		if (resource === "memory") {
			return this.handleMemory(method, segments.slice(1), searchParams, init);
		}
		if (resource === "observability") {
			return this.handleObservability(
				method,
				segments.slice(1),
				searchParams,
				init,
			);
		}
		if (
			resource === "notes" ||
			resource === "tasks" ||
			resource === "productivity"
		) {
			return errorResponse(
				404,
				"Productivity is disabled in the Android local runtime.",
			);
		}
		if (resource === "admin") {
			return this.handleAdmin(method, segments.slice(1), searchParams, init);
		}
		return errorResponse(404, "Unsupported local runtime API route.");
	}

	private handleAuth(
		method: string,
		segments: string[],
		init?: RequestInit,
	): Response {
		const [resource, idOrAction, action] = segments;
		if (resource === "me" && method === "GET") {
			return jsonResponse(principal(this.currentUser()));
		}
		if (resource === "refresh" && method === "POST") {
			return jsonResponse(authResponse(this.currentUser()));
		}
		if (resource === "demo-token" && method === "POST") {
			return jsonResponse({
				access_token: "android-local-token",
				token_type: "bearer",
				expires_in_seconds: 86400,
				issuer: "focus-agent-android-local-runtime",
			});
		}
		if (resource === "login" && method === "POST") {
			const body = parseJsonBody(init) as FocusAgentLoginRequest;
			const username = stringValue(body.username).trim();
			if (username) {
				this.currentUser().username = username;
				this.currentUser().display_name = username;
				this.persist();
			}
			return jsonResponse(authResponse(this.currentUser()));
		}
		if (resource === "register" && method === "POST") {
			const body = parseJsonBody(init) as Partial<FocusAgentCreateUserRequest>;
			const user = this.currentUser();
			user.username = nullableString(body.username) ?? user.username;
			user.display_name =
				nullableString(body.display_name) ?? user.display_name;
			user.tenant_id = nullableString(body.tenant_id) ?? user.tenant_id;
			user.updated_at = nowIso();
			this.persist();
			return jsonResponse(authResponse(user));
		}
		if (resource === "logout" && method === "POST") {
			return emptyResponse({ status: 204 });
		}
		if (resource === "change-password" && method === "POST") {
			this.currentUser().password_updated_at = nowIso();
			this.addAuditEvent("auth.change_password", "user", LOCAL_USER_ID);
			this.persist();
			return emptyResponse({ status: 204 });
		}
		if (resource === "sessions" && method === "GET") {
			return jsonResponse(this.sessionList(this.currentUser().user_id));
		}
		if (resource === "sessions" && action === "revoke" && method === "POST") {
			const session = this.state.sessions.find(
				(item) => item.session_id === idOrAction,
			);
			if (!session) return errorResponse(404, "Session not found.");
			session.revoked_at = nowIso();
			session.current = false;
			this.addAuditEvent("auth.session_revoke", "session", session.session_id);
			this.persist();
			return jsonResponse(session);
		}
		return errorResponse(404, "Unsupported local auth route.");
	}

	private handleConversations(
		method: string,
		segments: string[],
		init?: RequestInit,
	): Response {
		const [rootThreadId, action] = segments;
		if (!rootThreadId && method === "GET") {
			return jsonResponse({
				conversations: this.state.conversations,
			} satisfies FocusAgentConversationListResponse);
		}
		if (!rootThreadId && method === "POST") {
			const body = parseJsonBody(init) as FocusAgentCreateConversationRequest;
			const timestamp = nowIso();
			const threadId = this.nextId("thread", "local-thread");
			const title = nullableString(body.title) ?? "New local chat";
			this.state.threads[threadId] = newThreadState(threadId, threadId);
			const conversation: FocusAgentConversationSummary = {
				root_thread_id: threadId,
				title,
				is_archived: false,
				archived_at: null,
				created_at: timestamp,
				updated_at: timestamp,
			};
			this.state.conversations.unshift(conversation);
			this.persist();
			return jsonResponse(conversation);
		}
		const conversation = this.state.conversations.find(
			(item) => item.root_thread_id === rootThreadId,
		);
		if (!conversation) return errorResponse(404, "Conversation not found.");
		if (!action && method === "PATCH") {
			const body = parseJsonBody(init) as FocusAgentUpdateConversationRequest;
			conversation.title = stringValue(body.title).trim() || conversation.title;
			conversation.updated_at = nowIso();
			this.persist();
			return jsonResponse(conversation);
		}
		if (action === "archive" && method === "POST") {
			conversation.is_archived = true;
			conversation.archived_at = nowIso();
			conversation.updated_at = nowIso();
			this.persist();
			return jsonResponse(conversation);
		}
		if (action === "activate" && method === "POST") {
			conversation.is_archived = false;
			conversation.archived_at = null;
			conversation.updated_at = nowIso();
			this.persist();
			return jsonResponse(conversation);
		}
		return errorResponse(404, "Unsupported local conversation route.");
	}

	private handleThreads(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		const [threadId, resource, subresource, action] = segments;
		if (!threadId) return errorResponse(404, "Thread id is required.");
		const thread = this.state.threads[threadId];
		if (!thread) return errorResponse(404, "Thread not found.");
		if (!resource && method === "GET") {
			return jsonResponse(thread);
		}
		if (resource === "resolution" && method === "GET") {
			return jsonResponse(this.threadResolution(thread));
		}
		if (
			resource === "context" &&
			subresource === "preview" &&
			method === "POST"
		) {
			const body = parseJsonBody(init) as ThreadContextPreviewRequest;
			const previewMessages = body.draft_message
				? [...thread.messages, { type: "human", content: body.draft_message }]
				: thread.messages;
			return jsonResponse({
				context_usage: contextUsage(previewMessages),
			} satisfies ThreadContextPreviewResponse);
		}
		if (
			resource === "context" &&
			subresource === "compact" &&
			method === "POST"
		) {
			thread.rolling_summary = thread.messages
				.slice(-6)
				.map(
					(message) => `${message.type ?? "message"}: ${message.content ?? ""}`,
				)
				.join("\n")
				.slice(0, 1200);
			thread.context_usage = contextUsage(thread.messages);
			this.persist();
			return jsonResponse(thread);
		}
		if (resource === "branch-decisions" && !subresource && method === "GET") {
			const status = searchParams.get("status");
			const actionFilter = searchParams.get("action");
			const limit = searchParamNumber(searchParams, "limit", 20);
			const items = this.localBranchDecisions(thread.thread_id)
				.filter((item) => !status || item.status === status)
				.filter((item) => !actionFilter || item.action === actionFilter)
				.slice(0, limit);
			return jsonResponse({
				items,
				count: items.length,
			} satisfies FocusAgentBranchDecisionListResponse);
		}
		if (
			resource === "branch-decisions" &&
			subresource &&
			(action === "promote" || action === "dismiss") &&
			method === "POST"
		) {
			const body = parseJsonBody(init) as { reason?: string | null };
			const updated = this.updateLocalBranchDecision(
				thread,
				subresource,
				action === "promote" ? "promoted" : "dismissed",
				body.reason ?? null,
			);
			if (!updated) return errorResponse(404, "Branch decision not found.");
			this.persist();
			return jsonResponse(updated);
		}
		if (
			resource === "branch-actions" &&
			subresource &&
			action === "execute" &&
			method === "POST"
		) {
			const actionProposal = thread.branch_actions.find(
				(item) => item.action_id === subresource,
			);
			if (!actionProposal)
				return errorResponse(404, "Branch action not found.");
			actionProposal.status = "executed";
			actionProposal.executed_at = nowIso();
			const targetThreadId = actionProposal.target_parent_thread_id || threadId;
			const record = this.forkBranchRecord({
				parent_thread_id: targetThreadId,
				branch_name: actionProposal.suggested_branch_name ?? undefined,
				branch_role: actionProposal.branch_role,
			});
			if (!record) return errorResponse(404, "Parent thread not found.");
			actionProposal.navigation = {
				root_thread_id: record.root_thread_id,
				thread_id: record.child_thread_id,
			};
			const response: FocusAgentBranchActionExecuteResponse = {
				thread_state: thread,
				branch_action: actionProposal,
				branch_record: record,
				navigation: actionProposal.navigation,
			};
			this.persist();
			return jsonResponse(response);
		}
		if (
			resource === "branch-actions" &&
			subresource &&
			action === "dismiss" &&
			method === "POST"
		) {
			const actionProposal = thread.branch_actions.find(
				(item) => item.action_id === subresource,
			);
			if (!actionProposal)
				return errorResponse(404, "Branch action not found.");
			actionProposal.status = "dismissed";
			actionProposal.dismissed_at = nowIso();
			this.persist();
			return jsonResponse(thread);
		}
		return errorResponse(404, "Unsupported local thread route.");
	}

	private handleBranchDecisions(method: string, segments: string[]): Response {
		const [resource] = segments;
		if (resource === "config" && method === "GET") {
			return jsonResponse(this.branchDecisionConfig());
		}
		return errorResponse(404, "Unsupported local branch decision route.");
	}

	private handleBranches(
		method: string,
		segments: string[],
		init?: RequestInit,
	): Response {
		const [resource, threadIdOrAction, action] = segments;
		if (resource === "tree" && threadIdOrAction && method === "GET") {
			return jsonResponse(this.branchTree(threadIdOrAction));
		}
		if (resource === "fork" && method === "POST") {
			const body = parseJsonBody(init) as FocusAgentForkBranchRequest;
			const record = this.forkBranchRecord(body);
			return record
				? jsonResponse(record)
				: errorResponse(404, "Parent thread not found.");
		}
		if (!resource) return errorResponse(404, "Branch route is required.");
		const thread = this.state.threads[resource];
		if (!thread) return errorResponse(404, "Branch thread not found.");
		if (!action && method === "PATCH") {
			const body = parseJsonBody(init) as FocusAgentRenameBranchRequest;
			if (!thread.branch_meta) {
				return errorResponse(400, "Root thread cannot be renamed as a branch.");
			}
			thread.branch_meta.branch_name =
				stringValue(body.branch_name).trim() || thread.branch_meta.branch_name;
			this.persist();
			const record = threadBranchRecord(thread);
			return record
				? jsonResponse(record)
				: errorResponse(404, "Branch not found.");
		}
		if (threadIdOrAction === "archive" && method === "POST") {
			if (!thread.branch_meta) {
				return errorResponse(
					400,
					"Root thread cannot be archived as a branch.",
				);
			}
			thread.branch_meta.is_archived = true;
			thread.branch_meta.archived_at = nowIso();
			this.persist();
			return jsonResponse(threadBranchRecord(thread));
		}
		if (threadIdOrAction === "activate" && method === "POST") {
			if (!thread.branch_meta) {
				return errorResponse(
					400,
					"Root thread cannot be activated as a branch.",
				);
			}
			thread.branch_meta.is_archived = false;
			thread.branch_meta.archived_at = null;
			this.persist();
			return jsonResponse(threadBranchRecord(thread));
		}
		if (threadIdOrAction === "proposal" && method === "POST") {
			const proposal = this.prepareMergeProposal(thread);
			this.persist();
			return jsonResponse(proposal);
		}
		if (threadIdOrAction === "merge" && method === "POST") {
			const body = parseJsonBody(init) as FocusAgentApplyMergeDecisionRequest;
			return jsonResponse(this.applyMergeDecision(thread, body));
		}
		return errorResponse(404, "Unsupported local branch route.");
	}

	private handleNotes(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		const [noteId] = segments;
		if (!noteId && method === "GET") {
			return jsonResponse(this.noteList(searchParams));
		}
		if (!noteId && method === "POST") {
			const note = this.createNote(
				parseJsonBody(init) as Partial<FocusAgentCreateNoteRequest>,
			);
			return jsonResponse({ note } satisfies FocusAgentNoteResponse);
		}
		const note = this.state.notes.find((item) => item.note_id === noteId);
		if (!note) return errorResponse(404, "Note not found.");
		if (method === "GET") {
			return jsonResponse({ note } satisfies FocusAgentNoteResponse);
		}
		if (method === "PATCH") {
			this.updateNote(
				note,
				parseJsonBody(init) as Partial<FocusAgentUpdateNoteRequest>,
			);
			return jsonResponse({ note } satisfies FocusAgentNoteResponse);
		}
		return errorResponse(404, "Unsupported local note route.");
	}

	private handleTasks(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		const [taskId, action] = segments;
		if (!taskId && method === "GET") {
			return jsonResponse(this.taskList(searchParams));
		}
		if (!taskId && method === "POST") {
			const task = this.createTask(
				parseJsonBody(init) as Partial<FocusAgentCreateTaskRequest>,
			);
			return jsonResponse({ task } satisfies FocusAgentTaskResponse);
		}
		const task = this.state.tasks.find((item) => item.task_id === taskId);
		if (!task) return errorResponse(404, "Task not found.");
		if (!action && method === "PATCH") {
			this.updateTask(
				task,
				parseJsonBody(init) as Partial<FocusAgentUpdateTaskRequest>,
				"updated",
			);
			return jsonResponse({ task } satisfies FocusAgentTaskResponse);
		}
		if (action === "complete" && method === "POST") {
			this.updateTask(task, { status: "completed" }, "completed");
			return jsonResponse({ task } satisfies FocusAgentTaskResponse);
		}
		if (action === "archive" && method === "POST") {
			this.updateTask(task, { status: "archived" }, "archived");
			return jsonResponse({ task } satisfies FocusAgentTaskResponse);
		}
		if (action === "events" && method === "GET") {
			const items = this.state.taskEvents.filter(
				(item) => item.task_id === task.task_id,
			);
			return jsonResponse({
				items,
				count: items.length,
			} satisfies FocusAgentTaskEventListResponse);
		}
		return errorResponse(404, "Unsupported local task route.");
	}

	private handleProductivity(
		method: string,
		segments: string[],
		init?: RequestInit,
	): Response {
		const [resource, kind] = segments;
		if (resource === "capture" && kind === "note" && method === "POST") {
			const note = this.createNote(
				parseJsonBody(init) as Partial<FocusAgentCreateNoteRequest>,
			);
			return jsonResponse({ note } satisfies FocusAgentNoteResponse);
		}
		if (resource === "capture" && kind === "task" && method === "POST") {
			const task = this.createTask(
				parseJsonBody(init) as Partial<FocusAgentCreateTaskRequest>,
			);
			return jsonResponse({ task } satisfies FocusAgentTaskResponse);
		}
		return errorResponse(404, "Unsupported local productivity route.");
	}

	private handleMemory(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		const [memoryId, action] = segments;
		if (!memoryId && method === "GET") {
			const limit = searchParamNumber(searchParams, "limit", 50);
			const offset = searchParamNumber(searchParams, "offset", 0);
			const items = this.localMemoryRecords()
				.filter((item) =>
					searchParams.get("status")
						? item.status === searchParams.get("status")
						: true,
				)
				.filter((item) =>
					searchParams.get("root_thread_id")
						? item.root_thread_id === searchParams.get("root_thread_id")
						: true,
				)
				.slice(offset, offset + limit);
			return jsonResponse({
				items,
				count: items.length,
				filters: Object.fromEntries(searchParams.entries()),
				limit,
				offset,
				backend: "android-local",
				available: true,
				error: null,
			});
		}
		if (memoryId === "audit" && method === "GET") {
			const limit = searchParamNumber(searchParams, "limit", 50);
			const items = this.state.auditEvents
				.filter((event) => event.resource_type === "memory")
				.slice(0, limit)
				.map((event) => ({
					event_id: event.event_id,
					action: event.action,
					decision: event.decision,
					memory_id: event.resource_id,
					actor: event.actor_user_id,
					reason: event.reason,
					namespace: ["android-local"],
					user_id: event.actor_user_id,
					root_thread_id: null,
					source_thread_id: null,
					source_branch_id: null,
					request_id: event.request_id,
					data: event.metadata,
					created_at: event.created_at,
				}));
			return jsonResponse({
				items,
				count: items.length,
				filters: Object.fromEntries(searchParams.entries()),
				limit,
				backend: "android-local",
				available: true,
				error: null,
			});
		}
		if (memoryId === "candidates" && method === "GET") {
			const limit = searchParamNumber(searchParams, "limit", 50);
			return jsonResponse({
				items: [],
				count: 0,
				filters: Object.fromEntries(searchParams.entries()),
				limit,
				backend: "android-local",
				available: true,
				error: null,
			});
		}
		const item = this.localMemoryRecords().find(
			(record) => record.memory_id === memoryId,
		);
		if (!item) return errorResponse(404, "Memory record not found.");
		if (!action && method === "GET") {
			return jsonResponse({
				item,
				backend: "android-local",
				available: true,
				error: null,
			});
		}
		if (action === "audit" && method === "GET") {
			const limit = searchParamNumber(searchParams, "limit", 50);
			return jsonResponse({
				items: [],
				count: 0,
				filters: Object.fromEntries(searchParams.entries()),
				limit,
				backend: "android-local",
				available: true,
				error: null,
			});
		}
		if (action === "usage" && method === "GET") {
			return jsonResponse({
				memory_id: item.memory_id,
				usage: [],
				count: 0,
				backend: "android-local",
				available: true,
				error: null,
			});
		}
		if (action === "forget" && method === "POST") {
			const body = parseJsonBody(init) as { reason?: string | null };
			const auditId = this.nextId("audit", "local-audit");
			const forgottenMemoryIds = new Set(this.state.forgottenMemoryIds ?? []);
			forgottenMemoryIds.add(item.memory_id);
			this.state.forgottenMemoryIds = [...forgottenMemoryIds];
			this.state.auditEvents.unshift({
				event_id: auditId,
				actor_user_id: LOCAL_USER_ID,
				tenant_id: LOCAL_TENANT_ID,
				action: "memory.forget",
				resource_type: "memory",
				resource_id: item.memory_id,
				decision: "allowed",
				reason: body.reason ?? "android-local-memory-console",
				metadata: { backend: "android-local" },
				request_id: null,
				created_at: nowIso(),
			});
			this.persist();
			return jsonResponse({
				memory_id: item.memory_id,
				forgotten: true,
				status: "forgotten",
				tombstone_id: auditId,
				audit_id: auditId,
				decision: { reason: body.reason ?? null },
			});
		}
		return errorResponse(404, "Unsupported local memory route.");
	}

	private handleObservability(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		const [resource, subresource, action, nestedAction] = segments;
		if (resource === "overview" && method === "GET") {
			return jsonResponse(this.localObservabilityOverview(searchParams));
		}
		if (resource !== "trajectory") {
			return errorResponse(404, "Unsupported local observability route.");
		}
		if (!subresource && method === "GET") {
			return jsonResponse(this.localTrajectoryList(searchParams));
		}
		if (subresource === "stats" && method === "GET") {
			return jsonResponse({
				filters: Object.fromEntries(searchParams.entries()),
				stats: this.localTrajectoryStats(),
			});
		}
		if (
			subresource === "batch" &&
			action === "promote-preview" &&
			method === "POST"
		) {
			return jsonResponse({
				items: [],
				count: 0,
				filters: {},
				limit: 50,
				offset: 0,
				jsonl: "",
			});
		}
		if (
			subresource === "batch" &&
			action === "replay-compare" &&
			method === "POST"
		) {
			return jsonResponse({
				results: [],
				summary: {
					total: 0,
					passed: 0,
					failed: 0,
					source_failed: 0,
					tool_path_changed: 0,
				},
				filters: {},
				limit: 50,
				offset: 0,
			});
		}
		const detail = this.localTrajectoryDetail(subresource);
		if (!detail) return errorResponse(404, "Trajectory turn not found.");
		if (!action && method === "GET") {
			return jsonResponse({ item: detail });
		}
		if (action === "replay" && method === "POST") {
			const body = parseJsonBody(init) as { model?: string | null };
			return jsonResponse(this.localTrajectoryReplay(detail, body.model));
		}
		if (action === "promote" && method === "POST") {
			return jsonResponse(this.localTrajectoryPromotion(detail));
		}
		if (nestedAction) {
			return errorResponse(404, "Unsupported local trajectory route.");
		}
		return errorResponse(404, "Unsupported local trajectory route.");
	}

	private handleAgent(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		const [resource, subresource, third, fourth] = segments;
		const limit = searchParamNumber(searchParams, "limit", 50);
		if (resource === "capabilities" && method === "GET") {
			const items = this.localCapabilities();
			return jsonResponse({ items, count: items.length });
		}
		if (resource === "toolsets" && method === "GET") {
			const capabilities = this.localCapabilities();
			const toolsets = new Map<string, typeof capabilities>();
			for (const capability of capabilities) {
				const toolset = capability.toolset || "other";
				toolsets.set(toolset, [...(toolsets.get(toolset) ?? []), capability]);
			}
			return jsonResponse({
				items: [...toolsets.entries()].map(([name, items]) => ({
					name,
					description: `Android-local ${name} tools.`,
					tools: items.map((item) => item.name),
					count: items.length,
					provider_ids: name === "web" ? ["android-local-web"] : [],
					risk_levels: [...new Set(items.map((item) => item.risk_level))],
					allowed_roles: ["planner", "executor", "critic"],
					intent_policies: ["allow"],
					requires_network: items.some((item) => item.requires_network),
					requires_workspace_write: items.some(
						(item) => item.requires_workspace_write,
					),
					side_effect: items.some((item) => item.side_effect),
					requires_approval: items.some((item) => item.requires_approval),
				})),
				count: toolsets.size,
			});
		}
		if (
			resource === "tool-router" &&
			subresource === "route" &&
			method === "POST"
		) {
			const body = parseJsonBody(init) as {
				available_tools?: string[];
				role?: string;
				tool_policy?: string;
			};
			const enabledToolNames = this.localCapabilities().map(
				(item) => item.name,
			);
			const availableTools = stringArray(body.available_tools);
			const allowed = availableTools.length
				? availableTools.filter((toolName) =>
						enabledToolNames.includes(toolName),
					)
				: enabledToolNames;
			const denied = availableTools.filter(
				(toolName) => !enabledToolNames.includes(toolName),
			);
			return jsonResponse({
				plan: {
					allowed_tools: allowed,
					denied_tools: denied,
					decisions: [
						...allowed.map((toolName) => ({
							name: toolName,
							allowed: true,
							reason: "Enabled in Android local tool config.",
							role: body.role ?? "executor",
							tool_policy: body.tool_policy ?? "execution",
						})),
						...denied.map((toolName) => ({
							name: toolName,
							allowed: false,
							reason: "Disabled or unavailable in Android local runtime.",
							role: body.role ?? "executor",
							tool_policy: body.tool_policy ?? "execution",
						})),
					],
					runtime: "android-local",
				},
			});
		}
		if (
			resource === "tool-router" &&
			subresource === "decisions" &&
			method === "GET"
		) {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		if (resource === "roles" && subresource === "policy" && method === "GET") {
			return jsonResponse(this.localRolePolicy());
		}
		if (
			resource === "roles" &&
			subresource === "dry-run" &&
			method === "POST"
		) {
			const body = parseJsonBody(init) as { message?: string };
			return jsonResponse({
				policy: this.localRolePolicy(),
				plan: {
					role: "planner",
					decisions: [this.localRoleDecision(body.message ?? "", "planner")],
					reason: "Android local runtime uses a lightweight role router.",
					message: body.message ?? "",
				},
			});
		}
		if (
			resource === "roles" &&
			subresource === "decisions" &&
			method === "GET"
		) {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		if (
			resource === "skills" &&
			subresource === "catalog" &&
			method === "GET"
		) {
			const items = this.localSkillCatalogItems();
			return jsonResponse({ items, count: items.length });
		}
		if (
			resource === "skills" &&
			subresource === "select" &&
			method === "POST"
		) {
			const body = parseJsonBody(init) as {
				message?: string;
				skill_hints?: string[];
			};
			const selected = this.localSelectedSkills(
				body.message ?? "",
				stringArray(body.skill_hints),
			);
			const matchedTriggers = [
				...new Set(selected.flatMap((skill) => stringArray(skill.triggers))),
			];
			return jsonResponse({
				skill_ids: selected.map((skill) => String(skill.skill_id)),
				stripped_message: body.message ?? "",
				prompt_mode: selected[0]?.prompt_mode ?? null,
				selection_source: "android-local",
				matched_triggers: matchedTriggers,
				semantic_candidates: selected.map((skill, index) => ({
					skill_id: skill.skill_id,
					score: index === 0 ? 0.82 : 0.65,
					matched_terms: stringArray(skill.triggers),
					auto_activate: index === 0,
					rationale: "Matched by Android local skill triggers.",
				})),
				confidence: selected.length ? 0.82 : 0.5,
				rationale: "Android local runtime selected built-in local skills.",
				semantic_enabled: false,
				semantic_threshold: 0,
			});
		}
		if (
			resource === "skills" &&
			subresource === "selections" &&
			!third &&
			method === "GET"
		) {
			return jsonResponse(this.localAgentEmptyList(limit));
		}
		if (
			resource === "skills" &&
			subresource &&
			third === "preference" &&
			method === "PATCH"
		) {
			const body = parseJsonBody(init) as {
				enabled?: boolean | null;
				pinned?: boolean | null;
			};
			const skill =
				this.localSkillCatalogItems().find(
					(item) => item.skill_id === subresource || item.name === subresource,
				) ?? this.localSkillCatalogItems()[0];
			return jsonResponse({
				skill: {
					...skill,
					enabled: body.enabled ?? skill?.enabled ?? true,
					pinned: body.pinned ?? skill?.pinned ?? false,
					disabled_until: null,
				},
			});
		}
		if (
			resource === "skills" &&
			subresource === "selections" &&
			fourth === "feedback"
		) {
			return jsonResponse({ items: [], count: 0 });
		}
		if (
			resource === "feedback" &&
			subresource === "trend" &&
			method === "GET"
		) {
			return jsonResponse({
				negative_feedback_count: 0,
				merge_review_apply_success_rate: null,
				merge_review_conflict_rate: null,
				skill_low_confidence_rate: null,
				skill_override_rate: null,
				context_high_drift_count: 0,
				notes_tasks_capture_count: 0,
				top_failing_trajectory_samples: [],
				generated_at: nowIso(),
			});
		}
		if (resource === "memory") {
			return this.handleLocalAgentMemory(method, subresource, third, limit);
		}
		if (resource === "delegation") {
			return this.handleLocalAgentDelegation(method, subresource, limit, init);
		}
		if (resource === "model-router") {
			return this.handleLocalAgentModelRouter(method, subresource, limit, init);
		}
		if (resource === "self-repair") {
			return subresource === "failures" && method === "GET"
				? jsonResponse(this.localAgentEmptyList(limit))
				: jsonResponse({ preview: { items: [], runtime: "android-local" } });
		}
		if (resource === "review-queue") {
			if (!subresource && method === "GET")
				return jsonResponse(this.localAgentEmptyList(limit));
			return jsonResponse({
				item: { id: subresource, status: third ?? "decided" },
			});
		}
		if (resource === "context") {
			return this.handleLocalAgentContext(method, subresource, limit, init);
		}
		if (resource === "task-ledger") {
			return this.handleLocalAgentTaskLedger(method, subresource, limit, init);
		}
		if (resource === "artifacts") {
			if (!subresource && method === "GET")
				return jsonResponse(this.localAgentEmptyList(limit));
			return jsonResponse({
				result: { artifacts: [], runtime: "android-local" },
			});
		}
		if (resource === "critic") {
			if (subresource === "verdicts" && method === "GET") {
				return jsonResponse(this.localAgentEmptyList(limit));
			}
			return jsonResponse({
				result: { verdict: "pass", runtime: "android-local" },
			});
		}
		return errorResponse(404, "Unsupported local agent governance route.");
	}

	private async handleAdmin(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Promise<Response> {
		const [resource, userId, subresource, action] = segments;
		if (resource === "users") {
			return this.handleAdminUsers(
				method,
				userId,
				subresource,
				action,
				searchParams,
				init,
			);
		}
		if (resource === "audit-events" && method === "GET") {
			return jsonResponse(this.auditEvents(searchParams));
		}
		if (resource === "config") {
			return this.handleAdminConfig(method, userId, init);
		}
		return errorResponse(404, "Unsupported local admin route.");
	}

	private handleAdminUsers(
		method: string,
		userId: string | undefined,
		subresource: string | undefined,
		action: string | undefined,
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		if (!userId && method === "GET") {
			return jsonResponse(this.userList(searchParams));
		}
		if (!userId && method === "POST") {
			const body = parseJsonBody(init) as FocusAgentCreateUserRequest;
			const user = localUser({
				user_id:
					stringValue(body.user_id).trim() ||
					this.nextId("session", "local-user"),
				username: nullableString(body.username),
				display_name: nullableString(body.display_name),
				email: nullableString(body.email),
				tenant_id: nullableString(body.tenant_id) ?? LOCAL_TENANT_ID,
				status: nullableString(body.status) ?? "active",
				roles: stringArray(body.roles),
				metadata: isRecord(body.metadata) ? body.metadata : {},
			});
			this.state.users.push(user);
			this.addAuditEvent("admin.user_create", "user", user.user_id);
			this.persist();
			return jsonResponse(user);
		}
		const user = this.state.users.find((item) => item.user_id === userId);
		if (!user) return errorResponse(404, "User not found.");
		if (!subresource && method === "GET") {
			return jsonResponse(user);
		}
		if (!subresource && method === "PATCH") {
			const body = parseJsonBody(init) as FocusAgentUpdateUserRequest;
			user.username = nullableString(body.username) ?? user.username;
			user.display_name =
				nullableString(body.display_name) ?? user.display_name;
			user.email = nullableString(body.email) ?? user.email;
			user.tenant_id = nullableString(body.tenant_id) ?? user.tenant_id;
			user.metadata = isRecord(body.metadata) ? body.metadata : user.metadata;
			user.updated_at = nowIso();
			this.addAuditEvent("admin.user_update", "user", user.user_id);
			this.persist();
			return jsonResponse(user);
		}
		if (subresource === "status" && method === "POST") {
			const body = parseJsonBody(init) as FocusAgentUpdateUserStatusRequest;
			user.status = stringValue(body.status) || user.status;
			user.updated_at = nowIso();
			this.addAuditEvent("admin.user_status_update", "user", user.user_id);
			this.persist();
			return jsonResponse(user);
		}
		if (subresource === "roles" && method === "PUT") {
			const body = parseJsonBody(init) as FocusAgentUpdateUserRolesRequest;
			user.roles = stringArray(body.roles);
			user.updated_at = nowIso();
			this.addAuditEvent("admin.user_roles_update", "user", user.user_id);
			this.persist();
			return jsonResponse(user);
		}
		if (subresource === "password" && method === "POST") {
			user.password_updated_at = nowIso();
			user.updated_at = nowIso();
			this.addAuditEvent("admin.user_password_reset", "user", user.user_id);
			this.persist();
			return jsonResponse(user);
		}
		if (subresource === "sessions" && !action && method === "GET") {
			return jsonResponse(this.sessionList(user.user_id, searchParams));
		}
		if (
			subresource === "sessions" &&
			action === "revoke" &&
			method === "POST"
		) {
			const body = parseJsonBody(init) as { session_id?: string };
			const session = this.state.sessions.find(
				(item) =>
					item.user_id === user.user_id && item.session_id === body.session_id,
			);
			if (!session) return errorResponse(404, "Session not found.");
			session.revoked_at = nowIso();
			session.current = false;
			this.addAuditEvent(
				"admin.user_session_revoke",
				"session",
				session.session_id,
			);
			this.persist();
			return jsonResponse(session);
		}
		return errorResponse(404, "Unsupported local admin user route.");
	}

	private async handleAdminConfig(
		method: string,
		resource?: string,
		init?: RequestInit,
	): Promise<Response> {
		if (!resource && method === "GET") {
			return jsonResponse(this.adminConfigResponse());
		}
		if (resource === "models" && method === "PATCH") {
			const body = parseJsonBody(
				init,
			) as FocusAgentUpdateAdminModelConfigRequest;
			const models = this.state.adminConfig.models;
			models.default_model = body.default_model ?? models.default_model;
			models.helper_model = body.helper_model ?? models.helper_model;
			models.model_choices = body.model_choices ?? models.model_choices;
			if (body.providers) {
				const nextProviderIds = new Set<string>();
				models.providers = body.providers.map((provider) => {
					const id = provider.id.trim();
					nextProviderIds.add(id);
					const existing = models.providers.find((item) => item.id === id);
					const nextSecret = nullableString(provider.api_key_default);
					if (nextSecret) {
						this.modelSecrets[id] = { apiKey: nextSecret };
					}
					return {
						id,
						label: provider.label ?? existing?.label ?? id,
						backend_provider:
							provider.backend_provider ??
							existing?.backend_provider ??
							"openai-compatible",
						aliases: provider.aliases ?? existing?.aliases ?? [id],
						logo_slug: provider.logo_slug ?? existing?.logo_slug ?? null,
						logo_letter:
							provider.logo_letter ?? existing?.logo_letter ?? id[0] ?? null,
						base_url_env:
							provider.base_url_env ?? existing?.base_url_env ?? null,
						base_url_default:
							normalizedUrl(provider.base_url_default) ||
							existing?.base_url_default ||
							DEFAULT_PROVIDER_BASE_URL,
						base_url_configured: true,
						api_key_env: provider.api_key_env ?? existing?.api_key_env ?? null,
						api_key_configured: Boolean(
							(this.modelSecrets[id]?.apiKey ?? "").trim(),
						),
					};
				});
				for (const providerId of Object.keys(this.modelSecrets)) {
					if (!nextProviderIds.has(providerId)) {
						delete this.modelSecrets[providerId];
					}
				}
				await this.persistSecrets();
			}
			if (body.models) {
				models.models = body.models.map((item) => ({
					id: item.id,
					label: item.label ?? item.id,
					supports_thinking: item.supports_thinking ?? false,
					default_thinking_enabled: item.default_thinking_enabled ?? false,
					request_kwargs: item.request_kwargs ?? {},
					thinking_enabled_request_kwargs:
						item.thinking_enabled_request_kwargs ?? {},
					thinking_disabled_request_kwargs:
						item.thinking_disabled_request_kwargs ?? {},
					thinking_disabled_model_name:
						item.thinking_disabled_model_name ?? null,
					reasoning_effort: item.reasoning_effort ?? null,
					no_temperature: item.no_temperature ?? true,
					thinking_enable_extra_body_type:
						item.thinking_enable_extra_body_type ?? null,
					thinking_disable_extra_body_type:
						item.thinking_disable_extra_body_type ?? null,
					thinking_disable_switch_model:
						item.thinking_disable_switch_model ?? null,
				}));
			}
			this.touchAdminConfig("Admin model config updated locally.");
			this.persist();
			return jsonResponse(this.adminConfigResponse());
		}
		if (resource === "tools" && method === "PATCH") {
			const body = parseJsonBody(
				init,
			) as FocusAgentUpdateAdminToolConfigRequest;
			if (body.tools) {
				const existingTools = this.state.adminConfig.tools.tools;
				const defaultTools = defaultAdminConfig().tools.tools;
				const incomingTools = body.tools
					.filter((tool) => ANDROID_LOCAL_TOOL_NAME_SET.has(tool.name))
					.map((tool) => {
						const existing =
							existingTools.find((item) => item.name === tool.name) ??
							defaultTools.find((item) => item.name === tool.name);
						return {
							name: tool.name,
							label: tool.label ?? existing?.label ?? tool.name,
							description: tool.description ?? existing?.description ?? "",
							enabled: tool.enabled ?? existing?.enabled ?? true,
							settings: tool.settings ?? existing?.settings ?? {},
							metadata: tool.metadata ?? existing?.metadata ?? {},
						};
					});
				this.state.adminConfig.tools.tools = ANDROID_LOCAL_TOOL_NAMES.map(
					(toolName) =>
						incomingTools.find((tool) => tool.name === toolName) ??
						existingTools.find((tool) => tool.name === toolName) ??
						defaultTools.find((tool) => tool.name === toolName),
				).filter(
					(tool): tool is FocusAgentAdminConfig["tools"]["tools"][number] =>
						Boolean(tool),
				);
			}
			if (body.providers) {
				this.state.adminConfig.tools.providers = body.providers.map(
					(provider) => ({
						id: provider.id,
						enabled: provider.enabled ?? true,
						order: provider.order ?? null,
						metadata: provider.metadata ?? {},
						overrides: provider.overrides ?? [],
					}),
				);
			}
			this.touchAdminConfig("Admin tool config updated locally.");
			this.persist();
			return jsonResponse(this.adminConfigResponse());
		}
		if (resource === "policies" && method === "PATCH") {
			const body = parseJsonBody(
				init,
			) as FocusAgentUpdateAdminPolicyConfigRequest;
			this.state.adminConfig.policies.items = Object.entries(
				body.values ?? {},
			).map(([key, value]) => ({
				key,
				env_key: null,
				label: key,
				value,
				value_type: typeof value,
				source: "local",
				editable: true,
				sensitive: false,
				configured: true,
				requires_restart: false,
				description: null,
				options: [],
			}));
			this.touchAdminConfig("Admin policy config updated locally.");
			this.persist();
			return jsonResponse(this.adminConfigResponse());
		}
		return errorResponse(404, "Unsupported local admin config route.");
	}

	private handleV2(
		method: string,
		segments: string[],
		init?: RequestInit,
	): Response {
		const [resource, threadOrRunId, runsOrAction, streamOrResume, maybeStream] =
			segments;
		if (
			resource === "threads" &&
			runsOrAction === "runs" &&
			streamOrResume === "stream" &&
			method === "POST"
		) {
			const body = parseJsonBody(init) as FocusAgentHarnessRunRequest;
			return this.streamRun(threadOrRunId, body, init?.signal ?? undefined);
		}
		if (
			resource === "threads" &&
			runsOrAction === "runs" &&
			streamOrResume === "resume" &&
			maybeStream === "stream" &&
			method === "POST"
		) {
			return this.streamRun(
				threadOrRunId,
				{ message: "Resume local runtime turn." },
				init?.signal ?? undefined,
			);
		}
		if (resource === "runs" && runsOrAction === "stream" && method === "POST") {
			return sseResponse([], init?.signal ?? undefined);
		}
		if (resource === "runs" && runsOrAction === "cancel" && method === "POST") {
			const body = parseJsonBody(init) as FocusAgentHarnessRunCancelRequest;
			return jsonResponse({
				run: {
					run_id: threadOrRunId,
					status: body.action ?? "interrupt",
					updated_at: nowIso(),
				},
				thread_state: null,
			} satisfies FocusAgentHarnessRunResponse);
		}
		return errorResponse(404, "Unsupported local stream route.");
	}

	private streamRun(
		threadId: string,
		request: FocusAgentHarnessRunRequest,
		signal?: AbortSignal,
	): Response {
		const thread = this.state.threads[threadId];
		if (!thread) return errorResponse(404, "Thread not found.");
		const runId = this.nextId("run", "local-run");
		const timestamp = nowIso();
		const message = stringValue(request.message);
		const selectedModel =
			request.model ||
			this.state.adminConfig.models.default_model ||
			DEFAULT_MODEL_ID;
		let branchDecision: FocusAgentBranchDecisionEvent | null = null;
		if (message.trim()) {
			thread.messages.push({
				id: this.nextId("message", "local-message"),
				type: "human",
				content: message,
				created_at: timestamp,
			});
			branchDecision = this.recordLocalBranchDecision(thread, message, runId);
		}
		thread.selected_model = selectedModel;
		thread.selected_thinking_mode = request.thinking_mode || "disabled";
		thread.context_usage = contextUsage(thread.messages);
		thread.trace = {
			...(thread.trace ?? {}),
			last_run_id: runId,
			runtime: "android-local",
		};
		this.touchConversation(thread.root_thread_id, message);
		this.persist();

		const baseData = { run_id: runId, thread_id: thread.thread_id };
		const encoder = new TextEncoder();
		const body = new ReadableStream<Uint8Array>({
			start: async (controller) => {
				const send = (event: FocusAgentEvent) => {
					controller.enqueue(encoder.encode(sseFrame(event)));
				};
				try {
					if (signal?.aborted) {
						throw signal.reason ?? new DOMException("Aborted", "AbortError");
					}
					send({
						id: `${runId}:1`,
						event: "run.metadata",
						data: { ...baseData, sequence: 1, source_node: "local-runtime" },
					});
					send({
						id: `${runId}:2`,
						event: "run.status",
						data: { ...baseData, sequence: 2, phase: "running" },
					});
					send({
						id: `${runId}:3`,
						event: "reasoning.delta",
						data: {
							...baseData,
							delta: "Using the Android in-app local runtime.",
							completed: true,
							content: "Using the Android in-app local runtime.",
						},
					});

					const isChinese = /[\u3400-\u9fff]/.test(message);
					const webSearchEnabled =
						this.localToolEnabled("web_search") && shouldUseWebSearch(message);
					let currentUtcTimeResult: string | null = null;
					if (
						webSearchEnabled &&
						this.localToolEnabled("current_utc_time") &&
						shouldUseCurrentTimeTool(message)
					) {
						const timeToolCallId = `${runId}:current-utc-time`;
						currentUtcTimeResult = nowIso();
						send({
							id: `${runId}:time-tool-call-delta`,
							event: "tool.call.delta",
							data: {
								...baseData,
								sequence: 4,
								id: timeToolCallId,
								name: "current_utc_time",
								tool_call_id: timeToolCallId,
								args_delta: "{}",
								raw: {
									id: timeToolCallId,
									name: "current_utc_time",
									args: {},
								},
							},
						});
						send({
							id: `${runId}:time-tool-requested`,
							event: "tool.requested",
							data: {
								...baseData,
								sequence: 4,
								node: "android-local-runtime",
								tool_name: "current_utc_time",
								tool_call_id: timeToolCallId,
								args: {},
							},
						});
						thread.messages.push({
							id: this.nextId("message", "local-message"),
							type: "ai",
							content: "",
							created_at: currentUtcTimeResult,
							tool_calls: [
								{
									id: timeToolCallId,
									name: "current_utc_time",
									args: {},
									function: {
										name: "current_utc_time",
										arguments: "{}",
									},
								},
							],
						});
						thread.messages.push({
							id: this.nextId("message", "local-message"),
							type: "tool",
							content: currentUtcTimeResult,
							created_at: currentUtcTimeResult,
							name: "current_utc_time",
							status: "completed",
							tool_call_id: timeToolCallId,
						});
						send({
							id: `${runId}:time-tool-result`,
							event: "tool.result",
							data: {
								...baseData,
								sequence: 5,
								tool_name: "current_utc_time",
								tool_call_id: timeToolCallId,
								message: currentUtcTimeResult,
								output: currentUtcTimeResult,
							},
						});
					}
					const webFetchEnabled =
						this.localToolEnabled("web_fetch") && shouldUseWebFetch(message);
					const webFetchCallId = `${runId}:web-fetch`;
					const webFetchTargetUrl = webFetchUrl(message);
					let webFetchResult: LocalWebFetchResult | null = null;
					if (webFetchEnabled) {
						send({
							id: `${runId}:fetch-tool-call-delta`,
							event: "tool.call.delta",
							data: {
								...baseData,
								sequence: 4,
								id: webFetchCallId,
								name: "web_fetch",
								tool_call_id: webFetchCallId,
								args_delta: JSON.stringify({ url: webFetchTargetUrl }),
								raw: {
									id: webFetchCallId,
									name: "web_fetch",
									args: { url: webFetchTargetUrl },
								},
							},
						});
						send({
							id: `${runId}:fetch-tool-requested`,
							event: "tool.requested",
							data: {
								...baseData,
								sequence: 4,
								node: "android-local-runtime",
								tool_name: "web_fetch",
								tool_call_id: webFetchCallId,
								args: { url: webFetchTargetUrl },
							},
						});
						thread.messages.push({
							id: this.nextId("message", "local-message"),
							type: "ai",
							content: "",
							created_at: nowIso(),
							tool_calls: [
								{
									id: webFetchCallId,
									name: "web_fetch",
									args: { url: webFetchTargetUrl },
									function: {
										name: "web_fetch",
										arguments: JSON.stringify({ url: webFetchTargetUrl }),
									},
								},
							],
						});
						try {
							webFetchResult = await runLocalWebFetch(
								webFetchTargetUrl,
								signal,
							);
							thread.messages.push({
								id: this.nextId("message", "local-message"),
								type: "tool",
								content: JSON.stringify(webFetchResult),
								created_at: nowIso(),
								name: "web_fetch",
								status: "completed",
								tool_call_id: webFetchCallId,
							});
							send({
								id: `${runId}:fetch-tool-result`,
								event: "tool.result",
								data: {
									...baseData,
									sequence: 5,
									tool_name: "web_fetch",
									tool_call_id: webFetchCallId,
									message:
										webFetchResult.title ||
										`web_fetch completed for ${webFetchTargetUrl}`,
									output: webFetchResult,
								},
							});
						} catch (error) {
							abortIfRequested(signal);
							const messageText =
								error instanceof Error ? error.message : String(error);
							thread.messages.push({
								id: this.nextId("message", "local-message"),
								type: "tool",
								content: JSON.stringify({
									error: messageText,
									url: webFetchTargetUrl,
								}),
								created_at: nowIso(),
								name: "web_fetch",
								status: "failed",
								tool_call_id: webFetchCallId,
							});
							send({
								id: `${runId}:fetch-tool-error`,
								event: "tool.error",
								data: {
									...baseData,
									sequence: 5,
									tool_name: "web_fetch",
									tool_call_id: webFetchCallId,
									message: messageText,
									output: {
										error: messageText,
										url: webFetchTargetUrl,
									},
								},
							});
						}
					}
					const webSearchCallId = `${runId}:web-search`;
					const webSearchQueryText = webSearchQuery(
						message,
						currentUtcTimeResult,
					);
					let webSearchResult: LocalWebSearchResult | null = null;
					if (webSearchEnabled) {
						send({
							id: `${runId}:tool-call-delta`,
							event: "tool.call.delta",
							data: {
								...baseData,
								sequence: 4,
								id: webSearchCallId,
								name: "web_search",
								tool_call_id: webSearchCallId,
								args_delta: JSON.stringify({ query: webSearchQueryText }),
								raw: {
									id: webSearchCallId,
									name: "web_search",
									args: { query: webSearchQueryText },
								},
							},
						});
						send({
							id: `${runId}:tool-requested`,
							event: "tool.requested",
							data: {
								...baseData,
								sequence: 4,
								node: "android-local-runtime",
								tool_name: "web_search",
								tool_call_id: webSearchCallId,
								args: { query: webSearchQueryText },
							},
						});
						thread.messages.push({
							id: this.nextId("message", "local-message"),
							type: "ai",
							content: "",
							created_at: nowIso(),
							tool_calls: [
								{
									id: webSearchCallId,
									name: "web_search",
									args: { query: webSearchQueryText },
									function: {
										name: "web_search",
										arguments: JSON.stringify({
											query: webSearchQueryText,
										}),
									},
								},
							],
						});
						try {
							webSearchResult = await runLocalWebSearch(
								webSearchQueryText,
								signal,
							);
							thread.messages.push({
								id: this.nextId("message", "local-message"),
								type: "tool",
								content: JSON.stringify(webSearchResult),
								created_at: nowIso(),
								name: "web_search",
								status: "completed",
								tool_call_id: webSearchCallId,
							});
							send({
								id: `${runId}:tool-result`,
								event: "tool.result",
								data: {
									...baseData,
									sequence: 5,
									tool_name: "web_search",
									tool_call_id: webSearchCallId,
									message:
										webSearchResult.answer ||
										`web_search completed for ${webSearchQueryText}`,
									output: webSearchResult,
								},
							});
						} catch (error) {
							abortIfRequested(signal);
							const messageText =
								error instanceof Error ? error.message : String(error);
							thread.messages.push({
								id: this.nextId("message", "local-message"),
								type: "tool",
								content: JSON.stringify({
									error: messageText,
									query: webSearchQueryText,
								}),
								created_at: nowIso(),
								name: "web_search",
								status: "failed",
								tool_call_id: webSearchCallId,
							});
							send({
								id: `${runId}:tool-error`,
								event: "tool.error",
								data: {
									...baseData,
									sequence: 5,
									tool_name: "web_search",
									tool_call_id: webSearchCallId,
									message: messageText,
									output: {
										error: messageText,
										query: webSearchQueryText,
									},
								},
							});
						}
					}
					const localToolExecutions: LocalToolExecution[] = [];
					const localToolPlan = this.localAppToolPlan(thread, message);
					for (const [index, plannedTool] of localToolPlan.entries()) {
						const localToolCallId = `${runId}:${plannedTool.name}:${index + 1}`;
						send({
							id: `${localToolCallId}:call-delta`,
							event: "tool.call.delta",
							data: {
								...baseData,
								sequence: 6 + index,
								id: localToolCallId,
								name: plannedTool.name,
								tool_call_id: localToolCallId,
								args_delta: JSON.stringify(plannedTool.args),
								raw: {
									id: localToolCallId,
									name: plannedTool.name,
									args: plannedTool.args,
								},
							},
						});
						send({
							id: `${localToolCallId}:requested`,
							event: "tool.requested",
							data: {
								...baseData,
								sequence: 6 + index,
								node: "android-local-runtime",
								tool_name: plannedTool.name,
								tool_call_id: localToolCallId,
								args: plannedTool.args,
							},
						});
						thread.messages.push({
							id: this.nextId("message", "local-message"),
							type: "ai",
							content: "",
							created_at: nowIso(),
							tool_calls: [
								{
									id: localToolCallId,
									name: plannedTool.name,
									args: plannedTool.args,
									function: {
										name: plannedTool.name,
										arguments: JSON.stringify(plannedTool.args),
									},
								},
							],
						});
						const execution = this.executeLocalAppTool(
							thread,
							plannedTool.name,
							plannedTool.args,
						);
						localToolExecutions.push(execution);
						thread.messages.push({
							id: this.nextId("message", "local-message"),
							type: "tool",
							content: JSON.stringify(execution.output),
							created_at: nowIso(),
							name: plannedTool.name,
							status: "completed",
							tool_call_id: localToolCallId,
						});
						send({
							id: `${localToolCallId}:result`,
							event: "tool.result",
							data: {
								...baseData,
								sequence: 7 + index,
								tool_name: plannedTool.name,
								tool_call_id: localToolCallId,
								message: execution.message,
								output: execution.output,
							},
						});
					}
					const resolvedProvider = this.modelProvider(selectedModel);
					let source = "local-runtime";
					let reply = "";
					if (!resolvedProvider) {
						reply = webFetchResult
							? localReplyWithWebFetch(message, webFetchResult)
							: webSearchResult
								? localReplyWithWebSearch(message, webSearchResult)
								: localToolExecutions.length > 0
									? localReplyWithLocalTools(message, localToolExecutions)
									: missingProviderKeyReply(
											this.modelProviderLabel(selectedModel),
											isChinese,
										);
					} else {
						const { model, provider } = resolvedProvider;
						source = provider.id;
						try {
							reply = await postOpenAiCompatibleChatCompletion({
								messages: this.chatMessages(
									thread,
									webSearchResult,
									webFetchResult,
									localToolExecutions,
								),
								model,
								provider,
								signal,
							});
						} catch (error) {
							abortIfRequested(signal);
							reply = webFetchResult
								? localReplyWithWebFetch(message, webFetchResult)
								: webSearchResult
									? localReplyWithWebSearch(message, webSearchResult)
									: localToolExecutions.length > 0
										? localReplyWithLocalTools(message, localToolExecutions)
										: providerErrorMessage(error, isChinese);
						}
					}
					abortIfRequested(signal);
					if (!reply.trim()) {
						reply = localReply(message);
					}
					if (webSearchResult && deniesExecutedWebAccess(reply)) {
						reply = localReplyWithWebSearch(message, webSearchResult);
						source = "local-runtime";
					} else if (webFetchResult && deniesExecutedWebAccess(reply)) {
						reply = localReplyWithWebFetch(message, webFetchResult);
						source = "local-runtime";
					}

					thread.messages.push({
						id: this.nextId("message", "local-message"),
						type: "ai",
						content: reply,
						created_at: nowIso(),
						response_metadata: {
							model_name: selectedModel,
							provider: source,
							runtime: "android-local",
						},
						usage_metadata: {
							input_tokens: Math.ceil(message.length / 4),
							output_tokens: Math.ceil(reply.length / 4),
							total_tokens: Math.ceil((message.length + reply.length) / 4),
						},
					});
					thread.assistant_message = reply;
					thread.context_usage = contextUsage(thread.messages);
					this.persist();

					splitText(reply).forEach((delta, index) => {
						send({
							id: `${runId}:${index + 4}`,
							event: "message.delta",
							data: { ...baseData, delta, channel: "message" },
						});
					});
					send({
						id: `${runId}:message-completed`,
						event: "message.completed",
						data: { ...baseData, content: reply, source },
					});
					send({
						id: `${runId}:completed`,
						event: "run.completed",
						data: {
							...baseData,
							status: "completed",
							thread_state: clone(thread) as unknown as Record<string, unknown>,
							branch_action: branchDecision?.promoted_action_id
								? (thread.branch_actions.find(
										(action) =>
											action.action_id === branchDecision.promoted_action_id,
									) ?? null)
								: null,
							branch_decision: branchDecision,
						},
					});
					controller.close();
				} catch (error) {
					if (signal?.aborted) {
						controller.error(
							signal.reason ?? new DOMException("Aborted", "AbortError"),
						);
						return;
					}
					send({
						id: `${runId}:failed`,
						event: "run.failed",
						data: {
							...baseData,
							error: error instanceof Error ? error.message : String(error),
							message: "Android local runtime failed to complete the turn.",
						},
					});
					controller.close();
				}
			},
		});
		return new Response(body, { headers: SSE_HEADERS });
	}

	private modelsResponse(): FocusAgentModelsResponse {
		const defaultModel =
			this.state.adminConfig.models.default_model || DEFAULT_MODEL_ID;
		const configuredModels = this.state.adminConfig.models.models;
		const providers = this.adminConfigResponse().models.providers;
		const fallbackProvider = providers[0];
		const models =
			configuredModels.length > 0
				? configuredModels.map((item) => {
						const provider =
							this.providerConfigForModel(item.id)?.provider ??
							fallbackProvider;
						return {
							id: item.id,
							provider: provider?.id ?? DEFAULT_PROVIDER_ID,
							provider_label: provider?.label ?? "DeepSeek",
							provider_logo_slug: provider?.logo_slug ?? null,
							provider_logo_letter: provider?.logo_letter ?? "O",
							name: item.label ?? item.id,
							label: item.label ?? item.id,
							is_default: item.id === defaultModel,
							supports_thinking: Boolean(item.supports_thinking),
							default_thinking_enabled: Boolean(item.default_thinking_enabled),
						};
					})
				: [modelOption()];
		return { default_model: defaultModel, models };
	}

	private noteList(searchParams: URLSearchParams): FocusAgentNoteListResponse {
		const query = (searchParams.get("q") ?? "").trim().toLowerCase();
		const tags = searchParams.getAll("tag").filter(Boolean);
		const sourceKind = searchParams.get("source_kind");
		const includeArchived = searchParamBoolean(
			searchParams,
			"include_archived",
		);
		const limit = searchParamNumber(searchParams, "limit", 50);
		const offset = searchParamNumber(searchParams, "offset", 0);
		const items = this.state.notes.filter((note) => {
			const text = [note.title, note.body, ...note.tags]
				.join(" ")
				.toLowerCase();
			return (
				(includeArchived || !note.is_archived) &&
				(!query || text.includes(query)) &&
				(!sourceKind || note.source_kind === sourceKind) &&
				(tags.length === 0 || tags.every((tag) => note.tags.includes(tag)))
			);
		});
		return {
			items: items.slice(offset, offset + limit),
			count: items.length,
		};
	}

	private createNote(
		body: Partial<FocusAgentCreateNoteRequest>,
	): FocusAgentNote {
		const timestamp = nowIso();
		const note: FocusAgentNote = {
			note_id: this.nextId("note", "local-note"),
			user_id: LOCAL_USER_ID,
			title:
				nullableString(body.title) ??
				nullableString(body.body)?.slice(0, 80) ??
				"Untitled note",
			body: stringValue(body.body),
			tags: stringArray(body.tags),
			status: "active",
			source_thread_id: nullableString(body.source_thread_id),
			source_artifact_id: nullableString(body.source_artifact_id),
			source_kind: nullableString(
				body.source_kind,
			) as FocusAgentProductivitySourceKind | null,
			source_id: nullableString(body.source_id),
			source_url: nullableString(body.source_url),
			pinned_context: nullableString(body.pinned_context),
			captured_from: nullableString(body.captured_from),
			is_archived: false,
			metadata: metadataRecord(body.metadata),
			created_at: timestamp,
			updated_at: timestamp,
			archived_at: null,
		};
		this.state.notes.unshift(note);
		this.addAuditEvent("productivity.note_create", "note", note.note_id);
		this.persist();
		return note;
	}

	private updateNote(
		note: FocusAgentNote,
		body: Partial<FocusAgentUpdateNoteRequest>,
	): void {
		note.title = nullableString(body.title) ?? note.title;
		if (body.body !== undefined && body.body !== null) {
			note.body = stringValue(body.body);
		}
		if (body.tags !== undefined && body.tags !== null) {
			note.tags = stringArray(body.tags);
		}
		if (body.status === "active" || body.status === "archived") {
			note.status = body.status;
			note.is_archived = body.status === "archived";
		}
		if (typeof body.is_archived === "boolean") {
			note.is_archived = body.is_archived;
			note.status = body.is_archived ? "archived" : "active";
		}
		note.source_thread_id =
			body.source_thread_id === undefined
				? note.source_thread_id
				: nullableString(body.source_thread_id);
		note.source_artifact_id =
			body.source_artifact_id === undefined
				? note.source_artifact_id
				: nullableString(body.source_artifact_id);
		note.source_kind =
			body.source_kind === undefined
				? note.source_kind
				: (nullableString(
						body.source_kind,
					) as FocusAgentProductivitySourceKind | null);
		note.source_id =
			body.source_id === undefined
				? note.source_id
				: nullableString(body.source_id);
		note.source_url =
			body.source_url === undefined
				? note.source_url
				: nullableString(body.source_url);
		note.pinned_context =
			body.pinned_context === undefined
				? note.pinned_context
				: nullableString(body.pinned_context);
		note.captured_from =
			body.captured_from === undefined
				? note.captured_from
				: nullableString(body.captured_from);
		if (body.metadata !== undefined && body.metadata !== null) {
			note.metadata = metadataRecord(body.metadata);
		}
		note.archived_at = note.is_archived ? (note.archived_at ?? nowIso()) : null;
		note.updated_at = nowIso();
		this.addAuditEvent("productivity.note_update", "note", note.note_id);
		this.persist();
	}

	private taskList(searchParams: URLSearchParams): FocusAgentTaskListResponse {
		const status = searchParams.get("status") as FocusAgentTaskStatus | null;
		const sourceKind = searchParams.get("source_kind");
		const includeArchived = searchParamBoolean(
			searchParams,
			"include_archived",
		);
		const limit = searchParamNumber(searchParams, "limit", 50);
		const offset = searchParamNumber(searchParams, "offset", 0);
		const items = this.state.tasks.filter(
			(task) =>
				(includeArchived || task.status !== "archived") &&
				(!status || task.status === status) &&
				(!sourceKind || task.source_kind === sourceKind),
		);
		return {
			items: items.slice(offset, offset + limit),
			count: items.length,
		};
	}

	private createTask(
		body: Partial<FocusAgentCreateTaskRequest>,
	): FocusAgentTask {
		const timestamp = nowIso();
		const task: FocusAgentTask = {
			task_id: this.nextId("task", "local-task"),
			user_id: LOCAL_USER_ID,
			title: nullableString(body.title) ?? "Untitled task",
			description: stringValue(body.description),
			status: "todo",
			due_at: nullableString(body.due_at),
			priority: typeof body.priority === "number" ? body.priority : null,
			source_thread_id: nullableString(body.source_thread_id),
			source_note_id: nullableString(body.source_note_id),
			source_kind: nullableString(
				body.source_kind,
			) as FocusAgentProductivitySourceKind | null,
			source_id: nullableString(body.source_id),
			source_url: nullableString(body.source_url),
			pinned_context: nullableString(body.pinned_context),
			captured_from: nullableString(body.captured_from),
			assignee_user_id: nullableString(body.assignee_user_id),
			tags: stringArray(body.tags),
			metadata: metadataRecord(body.metadata),
			created_at: timestamp,
			updated_at: timestamp,
			completed_at: null,
			archived_at: null,
		};
		this.state.tasks.unshift(task);
		this.addTaskEvent(task, "created", { title: task.title });
		this.addAuditEvent("productivity.task_create", "task", task.task_id);
		this.persist();
		return task;
	}

	private updateTask(
		task: FocusAgentTask,
		body: Partial<FocusAgentUpdateTaskRequest>,
		eventKind: FocusAgentTaskEvent["kind"],
	): void {
		task.title = nullableString(body.title) ?? task.title;
		if (body.description !== undefined && body.description !== null) {
			task.description = stringValue(body.description);
		}
		if (
			body.status === "todo" ||
			body.status === "in_progress" ||
			body.status === "completed" ||
			body.status === "archived"
		) {
			task.status = body.status;
		}
		task.due_at =
			body.due_at === undefined ? task.due_at : nullableString(body.due_at);
		task.priority =
			body.priority === undefined
				? task.priority
				: typeof body.priority === "number"
					? body.priority
					: null;
		task.source_thread_id =
			body.source_thread_id === undefined
				? task.source_thread_id
				: nullableString(body.source_thread_id);
		task.source_note_id =
			body.source_note_id === undefined
				? task.source_note_id
				: nullableString(body.source_note_id);
		task.source_kind =
			body.source_kind === undefined
				? task.source_kind
				: (nullableString(
						body.source_kind,
					) as FocusAgentProductivitySourceKind | null);
		task.source_id =
			body.source_id === undefined
				? task.source_id
				: nullableString(body.source_id);
		task.source_url =
			body.source_url === undefined
				? task.source_url
				: nullableString(body.source_url);
		task.pinned_context =
			body.pinned_context === undefined
				? task.pinned_context
				: nullableString(body.pinned_context);
		task.captured_from =
			body.captured_from === undefined
				? task.captured_from
				: nullableString(body.captured_from);
		task.assignee_user_id =
			body.assignee_user_id === undefined
				? task.assignee_user_id
				: nullableString(body.assignee_user_id);
		if (body.tags !== undefined && body.tags !== null) {
			task.tags = stringArray(body.tags);
		}
		if (body.metadata !== undefined && body.metadata !== null) {
			task.metadata = metadataRecord(body.metadata);
		}
		task.completed_at =
			task.status === "completed" ? (task.completed_at ?? nowIso()) : null;
		task.archived_at =
			task.status === "archived" ? (task.archived_at ?? nowIso()) : null;
		task.updated_at = nowIso();
		this.addTaskEvent(task, eventKind, { status: task.status });
		this.addAuditEvent(`productivity.task_${eventKind}`, "task", task.task_id);
		this.persist();
	}

	private addTaskEvent(
		task: FocusAgentTask,
		kind: FocusAgentTaskEvent["kind"],
		data: Record<string, unknown>,
	): void {
		this.state.taskEvents.unshift({
			event_id: this.nextId("taskEvent", "local-task-event"),
			task_id: task.task_id,
			user_id: LOCAL_USER_ID,
			kind,
			data,
			created_at: nowIso(),
		});
	}

	private threadResolution(thread: ThreadStateResponse): ThreadResolution {
		const meta = thread.branch_meta;
		return {
			input_thread_id: thread.thread_id,
			root_thread_id: thread.root_thread_id,
			source_thread_id: thread.thread_id,
			branch_id: meta?.branch_id ?? null,
			is_root: thread.thread_id === thread.root_thread_id,
			branch_status: meta?.branch_status ?? "active",
			diagnostic: "resolved by android local runtime",
		};
	}

	private branchDecisionConfig(): FocusAgentBranchDecisionConfig {
		return {
			enabled: true,
			mode: "suggest",
			min_confidence: 0.7,
			split_threshold: 0.65,
			conclude_threshold: 0.7,
			merge_candidate_threshold: 0.75,
			rate_limit_per_hour: 3,
			recommendation_enabled: true,
			recommendation_mode: "suggest",
			recommendation_min_confidence: 0.72,
			recommendation_semantic_enabled: true,
			recommendation_semantic_model: null,
			recommendation_user_visible: true,
			recommendation_diagnostics: {
				code: "android_local_runtime",
				message:
					"Android local runtime uses a local heuristic for Focus Score.",
			},
			diagnostic: "Android local runtime",
		};
	}

	private localBranchDecisions(
		threadId: string,
	): FocusAgentBranchDecisionEvent[] {
		this.state.branchDecisions ??= {};
		return this.state.branchDecisions[threadId] ?? [];
	}

	private setLocalBranchDecisions(
		threadId: string,
		decisions: FocusAgentBranchDecisionEvent[],
	): void {
		this.state.branchDecisions ??= {};
		this.state.branchDecisions[threadId] = decisions.slice(0, 20);
	}

	private updateBranchDecisionSummary(thread: ThreadStateResponse): void {
		const decisions = this.localBranchDecisions(thread.thread_id);
		const latest = decisions[0] ?? null;
		const summary: FocusAgentBranchDecisionSummary = {
			latest_decision: latest,
			actionable: Boolean(
				latest &&
					latest.status === "suggested" &&
					!latest.promoted_action_id &&
					(latest.action === "fork_child_branch" ||
						latest.action === "fork_sibling_branch" ||
						latest.action === "split"),
			),
			pending_action_id:
				latest?.status === "promoted"
					? (latest.promoted_action_id ?? null)
					: null,
			dismissed_count: decisions.filter((item) => item.status === "dismissed")
				.length,
		};
		thread.branch_decision_summary = latest ? summary : null;
	}

	private updateLocalBranchDecision(
		thread: ThreadStateResponse,
		decisionId: string,
		status: "promoted" | "dismissed",
		dismissReason: string | null,
	): FocusAgentBranchDecisionEvent | null {
		const decisions = this.localBranchDecisions(thread.thread_id);
		const index = decisions.findIndex(
			(item) => item.decision_id === decisionId,
		);
		if (index < 0) return null;
		const decision = { ...decisions[index] };
		decision.status = status;
		decision.dismiss_reason =
			status === "dismissed" ? (dismissReason ?? "user_dismissed") : null;
		decision.updated_at = nowIso();
		decision.executed_at = decision.executed_at ?? nowIso();
		if (status === "promoted" && !decision.promoted_action_id) {
			this.createBranchActionFromDecision(
				thread,
				decision,
				decision.updated_at,
			);
		}
		decisions[index] = decision;
		this.setLocalBranchDecisions(thread.thread_id, decisions);
		this.updateBranchDecisionSummary(thread);
		return decision;
	}

	private createBranchActionFromDecision(
		thread: ThreadStateResponse,
		decision: FocusAgentBranchDecisionEvent,
		timestamp: string,
	): FocusAgentBranchActionProposal | null {
		if (
			decision.action !== "fork_child_branch" &&
			decision.action !== "fork_sibling_branch"
		) {
			return null;
		}
		const targetParentThreadId = decision.target_parent_thread_id;
		if (!targetParentThreadId) return null;
		const actionId = this.nextId("action", "local-branch-action");
		decision.promoted_action_id = actionId;
		const actionProposal: FocusAgentBranchActionProposal = {
			action_id: actionId,
			kind: decision.action,
			status: "pending",
			root_thread_id: thread.root_thread_id,
			source_thread_id: thread.thread_id,
			target_parent_thread_id: targetParentThreadId,
			suggested_branch_name: decision.suggested_branch_name,
			branch_role: "explore_alternatives",
			reason: decision.rationale,
			created_at: timestamp,
			executed_at: null,
			dismissed_at: null,
			failed_at: null,
			error: null,
			navigation: null,
			source: "branch_decision",
			source_decision_id: decision.decision_id,
			source_decision_status: decision.status,
			source_decision_mode: decision.mode,
			confidence: decision.score,
			rationale: decision.rationale,
			recommendation_user_visible: true,
			diagnostic: decision.diagnostic,
			handoff_message: localBranchHandoffMessage(
				decision.suggested_branch_name ?? "",
			),
		};
		thread.branch_actions = [...thread.branch_actions, actionProposal];
		return actionProposal;
	}

	private recordLocalBranchDecision(
		thread: ThreadStateResponse,
		message: string,
		runId: string,
	): FocusAgentBranchDecisionEvent | null {
		const compactMessage = message.replace(/\s+/g, " ").trim();
		if (!compactMessage) return null;
		const isChinese = /[\u3400-\u9fff]/.test(compactMessage);
		const priorMessages = thread.messages.slice(0, -1);
		const priorText = priorMessages
			.slice(-8)
			.map((item) => String(item.content ?? ""))
			.join(" ");
		const messageWords = textWords(compactMessage);
		const priorWords = new Set(textWords(priorText));
		const overlap = messageWords.filter((word) => priorWords.has(word)).length;
		const overlapRatio = messageWords.length
			? overlap / messageWords.length
			: 0;
		const explicitBranchCue = containsAny(compactMessage, [
			"new branch",
			"separate branch",
			"side branch",
			"branch off",
			"fork",
			"different topic",
			"another topic",
			"switch topic",
			"unrelated",
			"explore alternative",
			"alternative path",
			"what about",
			"新分支",
			"另起",
			"单独",
			"换个话题",
			"另外",
			"题外",
			"不相关",
			"另一条线",
		]);
		const stayCue = containsAny(compactMessage, [
			"continue current",
			"same branch",
			"stay in current",
			"keep going",
			"继续当前",
			"当前分支",
			"不用分支",
			"留在当前",
		]);
		let relatedness = priorWords.size
			? Math.min(0.95, Math.max(0.24, 0.34 + overlapRatio * 0.65))
			: 0.82;
		if (explicitBranchCue) relatedness = Math.min(relatedness, 0.34);
		if (stayCue) relatedness = Math.max(relatedness, 0.78);
		const hasConversationContext = priorMessages.length >= 2;
		const hasPendingAction = thread.branch_actions.some(
			(action) => action.status === "pending",
		);
		const shouldFork =
			!stayCue &&
			!hasPendingAction &&
			(explicitBranchCue ||
				(hasConversationContext &&
					messageWords.length >= 4 &&
					relatedness < 0.42));
		const action = shouldFork
			? thread.branch_meta
				? "fork_sibling_branch"
				: "fork_child_branch"
			: "continue_current";
		const targetParentThreadId = shouldFork
			? (thread.branch_meta?.parent_thread_id ?? thread.thread_id)
			: null;
		const score = shouldFork
			? Math.max(0.72, Math.min(0.96, 1 - relatedness))
			: relatedness;
		const timestamp = nowIso();
		const decisionId = this.nextId("action", "local-branch-decision");
		const diagnostic = {
			code: "android_local_focus_score",
			message: shouldFork
				? "Message appears better handled in a separate branch."
				: "Message appears related enough to continue in the current branch.",
			gate_reason: shouldFork ? "eligible" : "continue_current",
			threshold: shouldFork ? 0.72 : 0.65,
			semantic_classifier_status: "local_heuristic",
			semantic_relatedness: relatedness,
			semantic_relationship: shouldFork ? "topic_shift" : "related",
		};
		const signals = [
			{
				name: "semantic_relatedness",
				value: relatedness,
				score: relatedness,
				weight: 1,
				evidence_refs: [],
				rationale: "Estimated from lexical overlap with recent local context.",
			},
			{
				name: "explicit_branch_cue",
				value: explicitBranchCue,
				score: explicitBranchCue ? 1 : 0,
				weight: 0.5,
				evidence_refs: [],
				rationale:
					"Checks whether the user explicitly asked for a separate path.",
			},
		];
		const decision: FocusAgentBranchDecisionEvent = {
			decision_id: decisionId,
			user_id: LOCAL_USER_ID,
			root_thread_id: thread.root_thread_id,
			source_thread_id: thread.thread_id,
			branch_id: thread.branch_meta?.branch_id ?? null,
			recommendation_target: action,
			target_parent_thread_id: targetParentThreadId,
			suggested_branch_name: shouldFork
				? suggestedBranchName(compactMessage, isChinese)
				: null,
			confidence: score,
			action,
			status: shouldFork ? "promoted" : "skipped",
			mode: "suggest",
			score,
			threshold: shouldFork ? 0.72 : 0.65,
			signals,
			rationale: shouldFork
				? "Local Focus Score detected a likely topic shift."
				: "Local Focus Score keeps this turn on the current branch.",
			idempotency_key: `${thread.thread_id}:${runId}`,
			request_id: runId,
			trace_id: runId,
			promoted_action_id: null,
			dismiss_reason: null,
			error: null,
			recommendation_user_visible: true,
			diagnostic,
			metadata: {
				phase: "pre_turn",
				recommendation_target: action,
				recommendation_user_visible: true,
				semantic_classifier_status: "local_heuristic",
				semantic_relatedness: relatedness,
				semantic_relationship: shouldFork ? "topic_shift" : "related",
				semantic_reason: diagnostic.message,
				diagnostic,
				target_parent_thread_id: targetParentThreadId,
			},
			created_at: timestamp,
			updated_at: timestamp,
			executed_at: shouldFork ? timestamp : null,
		};
		if (shouldFork && targetParentThreadId) {
			const actionProposal = this.createBranchActionFromDecision(
				thread,
				decision,
				timestamp,
			);
			if (actionProposal) {
				actionProposal.handoff_message =
					localBranchHandoffMessage(compactMessage);
			}
		}
		this.setLocalBranchDecisions(thread.thread_id, [
			decision,
			...this.localBranchDecisions(thread.thread_id),
		]);
		this.updateBranchDecisionSummary(thread);
		return decision;
	}

	private branchTree(rootThreadId: string): BranchTreeResponse {
		const rootThread = this.state.threads[rootThreadId];
		const actualRootThread =
			rootThread?.root_thread_id &&
			this.state.threads[rootThread.root_thread_id]
				? this.state.threads[rootThread.root_thread_id]
				: rootThread;
		if (!actualRootThread) {
			return {
				root: this.branchTreeNode(newThreadState(rootThreadId, rootThreadId)),
				archived_branches: [],
			};
		}
		const root = this.branchTreeNode(actualRootThread);
		const archivedBranches: BranchTreeNode[] = [];
		const attachChildren = (node: BranchTreeNode) => {
			const children = Object.values(this.state.threads)
				.filter(
					(thread) => thread.branch_meta?.parent_thread_id === node.thread_id,
				)
				.map((thread) => this.branchTreeNode(thread));
			for (const child of children) {
				attachChildren(child);
				if (child.is_archived) {
					archivedBranches.push(child);
				} else {
					node.children.push(child);
				}
			}
		};
		attachChildren(root);
		return { root, archived_branches: archivedBranches };
	}

	private branchTreeNode(thread: ThreadStateResponse): BranchTreeNode {
		const meta = thread.branch_meta;
		const conversation = this.state.conversations.find(
			(item) => item.root_thread_id === thread.root_thread_id,
		);
		return {
			thread_id: thread.thread_id,
			root_thread_id: thread.root_thread_id,
			parent_thread_id: meta?.parent_thread_id ?? null,
			branch_id: meta?.branch_id ?? null,
			branch_name: meta?.branch_name ?? conversation?.title ?? "Main",
			branch_role: meta?.branch_role ?? "main",
			branch_status: meta?.branch_status ?? "active",
			is_archived: Boolean(meta?.is_archived),
			archived_at: meta?.archived_at ?? null,
			branch_depth: meta?.branch_depth ?? 0,
			fork_strategy: meta?.fork_strategy ?? "root",
			token_usage: {
				input_tokens: thread.context_usage?.used_tokens ?? 0,
				output_tokens: 0,
				total_tokens: thread.context_usage?.used_tokens ?? 0,
			},
			children: [],
		};
	}

	private forkBranchRecord(
		request: FocusAgentForkBranchRequest,
	): FocusAgentBranchRecord | null {
		const parentThread = this.state.threads[request.parent_thread_id];
		if (!parentThread) {
			return null;
		}
		const threadId = this.nextId("thread", "local-thread");
		const branchId = this.nextId("branch", "local-branch");
		const parentDepth = parentThread.branch_meta?.branch_depth ?? 0;
		const thread = newThreadState(threadId, parentThread.root_thread_id);
		thread.messages = clone(parentThread.messages);
		thread.context_usage = contextUsage(thread.messages);
		thread.branch_meta = {
			branch_id: branchId,
			root_thread_id: parentThread.root_thread_id,
			parent_thread_id: parentThread.thread_id,
			return_thread_id: parentThread.root_thread_id,
			branch_name:
				request.branch_name?.trim() ||
				(request.language === "zh" ? "本地分支" : "Local branch"),
			branch_role: request.branch_role ?? "explore_alternatives",
			branch_depth: parentDepth + 1,
			branch_status: "active",
			is_archived: false,
			archived_at: null,
			fork_checkpoint_id: request.fork_checkpoint_id ?? null,
			fork_strategy: request.name_source ?? "manual",
		};
		this.state.threads[threadId] = thread;
		this.persist();
		const record = threadBranchRecord(thread);
		if (!record) {
			return null;
		}
		return record;
	}

	private prepareMergeProposal(
		thread: ThreadStateResponse,
	): FocusAgentMergeProposal {
		const lastAssistantMessage = [...thread.messages]
			.reverse()
			.find((message) => message.type === "ai");
		const summary =
			String(lastAssistantMessage?.content ?? "").slice(0, 500) ||
			"Local branch summary.";
		const proposal: FocusAgentMergeProposal = {
			summary,
			key_findings: ["Conversation state was produced locally on Android."],
			open_questions: [],
			evidence_refs: [],
			artifacts: [],
			recommended_import_mode: "summary_only",
		};
		thread.merge_proposal = proposal;
		if (thread.branch_meta) {
			thread.branch_meta.branch_status = "awaiting_merge_review";
		}
		return proposal;
	}

	private applyMergeDecision(
		thread: ThreadStateResponse,
		request: FocusAgentApplyMergeDecisionRequest,
	): FocusAgentApplyMergeDecisionResponse {
		const approved = request.approved ?? true;
		const proposal = thread.merge_proposal ?? this.prepareMergeProposal(thread);
		const mode: MergeMode = request.mode ?? proposal.recommended_import_mode;
		const targetThreadId =
			request.target === "return_thread"
				? (thread.branch_meta?.return_thread_id ?? thread.root_thread_id)
				: thread.root_thread_id;
		const targetThread = this.state.threads[targetThreadId];
		thread.merge_decision = { ...request, approved, decided_at: nowIso() };
		if (approved && targetThread) {
			const imported = {
				branch_id: thread.branch_meta?.branch_id ?? thread.thread_id,
				branch_name: thread.branch_meta?.branch_name ?? "Local branch",
				mode,
				summary: request.proposal_overrides?.summary ?? proposal.summary,
				key_findings:
					request.proposal_overrides?.key_findings ?? proposal.key_findings,
				evidence_refs:
					request.proposal_overrides?.evidence_refs ?? proposal.evidence_refs,
				artifacts: request.proposal_overrides?.artifacts ?? proposal.artifacts,
				rationale: request.rationale ?? null,
			};
			targetThread.merge_queue.push(imported);
			targetThread.messages.push({
				id: this.nextId("message", "local-message"),
				type: "ai",
				content: `Merged local branch "${imported.branch_name}": ${imported.summary}`,
				created_at: nowIso(),
			});
			targetThread.context_usage = contextUsage(targetThread.messages);
			if (thread.branch_meta) {
				thread.branch_meta.branch_status = "merged";
			}
			this.persist();
			return { imported, target_thread_id: targetThreadId };
		}
		if (thread.branch_meta) {
			thread.branch_meta.branch_status = "discarded";
		}
		this.persist();
		return { imported: null, target_thread_id: targetThreadId };
	}

	private sessionList(
		userId: string,
		searchParams: URLSearchParams = new URLSearchParams(),
	): FocusAgentSessionListResponse {
		const includeRevoked = searchParams.get("include_revoked") === "true";
		const items = this.state.sessions.filter(
			(session) =>
				session.user_id === userId && (includeRevoked || !session.revoked_at),
		);
		return { items, count: items.length };
	}

	private userList(searchParams: URLSearchParams): FocusAgentUserListResponse {
		const query = (searchParams.get("query") ?? "").toLowerCase();
		const status = searchParams.getAll("status").filter(Boolean);
		const role = searchParams.getAll("role").filter(Boolean);
		const tenantId = searchParams.get("tenant_id");
		const limit = Number(searchParams.get("limit") ?? 50);
		const offset = Number(searchParams.get("offset") ?? 0);
		const items = this.state.users.filter((user) => {
			const text = [user.user_id, user.username, user.display_name, user.email]
				.join(" ")
				.toLowerCase();
			return (
				(!query || text.includes(query)) &&
				(!tenantId || user.tenant_id === tenantId) &&
				(status.length === 0 || status.includes(user.status)) &&
				(role.length === 0 || role.some((item) => user.roles.includes(item)))
			);
		});
		return {
			items: items.slice(offset, offset + limit),
			count: items.length,
			limit,
			offset,
		};
	}

	private auditEvents(
		searchParams: URLSearchParams,
	): FocusAgentAuditEventListResponse {
		const actor = searchParams.get("actor_user_id");
		const resourceType = searchParams.get("resource_type");
		const resourceId = searchParams.get("resource_id");
		const decision = searchParams.get("decision");
		const limit = Number(searchParams.get("limit") ?? 50);
		const offset = Number(searchParams.get("offset") ?? 0);
		const items = this.state.auditEvents.filter(
			(event) =>
				(!actor || event.actor_user_id === actor) &&
				(!resourceType || event.resource_type === resourceType) &&
				(!resourceId || event.resource_id === resourceId) &&
				(!decision || event.decision === decision),
		);
		return {
			items: items.slice(offset, offset + limit),
			count: items.length,
			limit,
			offset,
		};
	}

	private touchConversation(rootThreadId: string, message: string): void {
		const conversation = this.state.conversations.find(
			(item) => item.root_thread_id === rootThreadId,
		);
		if (!conversation) return;
		conversation.updated_at = nowIso();
		if (
			message.trim() &&
			(!conversation.title || conversation.title === "New local chat")
		) {
			conversation.title = message.trim().slice(0, 48);
		}
	}

	private touchAdminConfig(message: string): void {
		this.state.adminConfig.updated_at = nowIso();
		this.state.adminConfig.updated_by = LOCAL_USER_ID;
		this.state.adminConfig.message = message;
		this.addAuditEvent("admin.config_update", "config", "local-runtime", {
			message,
		});
	}
}
