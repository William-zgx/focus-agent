import type {
	FocusAgentAdminConfig,
	FocusAgentBranchRecord,
	FocusAgentModelOption,
	FocusAgentPrincipalResponse,
	FocusAgentUser,
	ThreadStateResponse,
} from "@focus-agent/web-sdk";
import {
	ANDROID_LOCAL_TOOL_NAME_SET,
	DEFAULT_MODEL_ID,
	DEFAULT_PROVIDER_BASE_URL,
	DEFAULT_PROVIDER_ID,
	LOCAL_RUNTIME_ACCESS_MODE,
	LOCAL_TENANT_ID,
	LOCAL_USER_ID,
} from "./constants";
import { clone, contextUsage, isRecord, nowIso } from "./helpers";
import { ANDROID_LOCAL_SKILLS } from "./skills";
import type { LocalGitCommit, LocalRuntimeState } from "./types";

export function localUser(
	overrides: Partial<FocusAgentUser> = {},
): FocusAgentUser {
	const timestamp = nowIso();
	return {
		user_id: LOCAL_USER_ID,
		username: "android-local",
		display_name: "Android Local",
		email: "local@focus-agent.invalid",
		tenant_id: LOCAL_TENANT_ID,
		status: "active",
		roles: [],
		auth_provider: "device-local",
		created_at: timestamp,
		updated_at: timestamp,
		last_seen_at: timestamp,
		last_login_at: null,
		password_updated_at: null,
		metadata: {
			runtime: "android-local",
			access_mode: LOCAL_RUNTIME_ACCESS_MODE,
			device_local_configuration: true,
		},
		...overrides,
	};
}

export function defaultWorkspaceFiles(): Record<string, string> {
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

export function defaultGitCommits(timestamp = nowIso()): LocalGitCommit[] {
	return [
		{
			hash: "androidlocal0001",
			subject: "Initialize Android local workspace",
			author: "Focus Agent Android",
			date: timestamp,
		},
	];
}

export function principal(user: FocusAgentUser): FocusAgentPrincipalResponse {
	return {
		user_id: user.user_id,
		tenant_id: user.tenant_id,
		scopes: ["chat", "branches", "device-local-config"],
		auth_enabled: false,
		user,
		roles: user.roles,
		permissions: ["chat:write", "branches:write", "device-local:configure"],
		is_admin: false,
	};
}

export function modelOption(): FocusAgentModelOption {
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

export function configSource(path = "android-local-runtime") {
	return {
		path,
		exists: true,
		writable: true,
	};
}

export function localAdminTool(
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

export function defaultAdminSkillConfig(): FocusAgentAdminConfig["skills"] {
	return {
		source: configSource("android-local-runtime/skills"),
		enabled: true,
		install_directory: configSource("android-local-runtime/skills/install"),
		skill_directories: [configSource("android-local-runtime/skills/builtin")],
		disabled_skill_ids: [],
		sources_enabled: ["android-local"],
		source_locations: [],
		trusted_sources: ["android-local"],
		sources: [
			{
				source_id: "android-local",
				source_type: "builtin",
				label: "Android local runtime",
				enabled: true,
				trusted: true,
				location: null,
				metadata: { runtime: "android-local" },
			},
		],
		catalog: ANDROID_LOCAL_SKILLS.map((skill) => ({
			skill_id: skill.skill_id,
			description: skill.description,
			enabled: true,
			triggers: skill.triggers,
			aliases: skill.aliases ?? [],
			localized_triggers: skill.localized_triggers ?? [],
			domains: skill.domains ?? [],
			intents: skill.intents ?? [],
			when_to_use: skill.when_to_use,
			primary_tools: skill.primary_tools ?? [],
			recommended_tools: skill.recommended_tools,
			prompt_mode: skill.prompt_mode,
			path: `android-local://${skill.skill_id}`,
			source_id: skill.source_id,
			source_type: "builtin",
			version: null,
			trust_level: "trusted",
			install_state: "installed",
			provenance: "android-local-runtime",
			checksum: null,
			capability_requirements: [],
		})),
		semantic_match_enabled: true,
		semantic_match_threshold: 0.25,
		refresh: {
			available: true,
			refreshed: false,
			previous_count: null,
			count: ANDROID_LOCAL_SKILLS.length,
		},
		requires_restart: false,
	};
}

export function defaultAdminConfig(): FocusAgentAdminConfig {
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
					"workspace_tree",
					"工作区树",
					"以缩进树形式展示 Android App 内虚拟工作区目录结构。",
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
		skills: defaultAdminSkillConfig(),
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

export function newThreadState(
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
		active_skills: [],
		messages,
		interrupts: [],
		branch_actions: [],
		branch_decision_summary: null,
		trace: {},
		context_usage: contextUsage(messages),
	};
}

export function initialState(): LocalRuntimeState {
	const timestamp = nowIso();
	const user = localUser({
		created_at: timestamp,
		updated_at: timestamp,
		last_seen_at: timestamp,
	});
	const rootThreadId = "local-thread-0001";
	const rootThread = newThreadState(rootThreadId, rootThreadId);
	const workspaceFiles = defaultWorkspaceFiles();
	return {
		accessMode: LOCAL_RUNTIME_ACCESS_MODE,
		version: 2,
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
			session: 1,
			task: 1,
			taskEvent: 1,
			thread: 2,
		},
		sessions: [],
		taskEvents: [],
		tasks: [],
		threads: { [rootThreadId]: rootThread },
		users: [user],
		workspaceBaseFiles: clone(workspaceFiles),
		workspaceFiles,
	};
}

export function normalizeStoredState(
	value: LocalRuntimeState,
): LocalRuntimeState {
	value.accessMode = LOCAL_RUNTIME_ACCESS_MODE;
	value.version = 2;
	value.users = [localUser()];
	value.sessions = [];
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
		"workspace_tree",
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
	const defaultSkills = defaultAdminSkillConfig();
	value.adminConfig.skills ??= defaultSkills;
	value.adminConfig.skills.catalog = defaultSkills.catalog;
	value.adminConfig.skills.sources = defaultSkills.sources;
	value.adminConfig.skills.refresh = defaultSkills.refresh;
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

export function threadBranchRecord(
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
