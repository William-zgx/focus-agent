import type {
	FocusAgentAdminConfig,
	FocusAgentAdminConfigProvider,
	FocusAgentAdminConfigValue,
	FocusAgentAdminModelConfigEntry,
	FocusAgentAdminToolConfigEntry,
	FocusAgentAdminToolProviderConfig,
} from "@focus-agent/web-sdk";

export type EditableConfigSection = "models" | "policies" | "tools";
export type ConfigSection = EditableConfigSection | "system";
export type PolicyDraftValue = boolean | string;

export type ModelProviderDraft = {
	id: string;
	label: string;
	backendProvider: string;
	aliases: string;
	logoSlug: string;
	logoLetter: string;
	baseUrlEnv: string;
	baseUrlDefault: string;
	baseUrlConfigured: boolean;
	apiKeyEnv: string;
	apiKeyConfigured: boolean;
};

export type ModelEntryDraft = {
	id: string;
	label: string;
	supportsThinking: boolean;
	defaultThinkingEnabled: boolean;
	reasoningEffort: string;
	noTemperature: boolean;
	original: FocusAgentAdminModelConfigEntry;
};

export type ModelDraft = {
	reason: string;
	defaultModel: string;
	helperModel: string;
	modelChoices: string[];
	providers: ModelProviderDraft[];
	models: ModelEntryDraft[];
};

export type ToolEntryDraft = {
	name: string;
	enabled: boolean;
	label: string;
	description: string;
	original: FocusAgentAdminToolConfigEntry;
};

export type ToolProviderDraft = {
	id: string;
	enabled: boolean;
	order: string;
	overrides: string;
	metadata: Record<string, unknown>;
};

export type ToolDraft = {
	reason: string;
	tools: ToolEntryDraft[];
	providers: ToolProviderDraft[];
};

export type PolicyDraft = {
	reason: string;
	values: Record<string, PolicyDraftValue>;
};

export const EMPTY_SELECT_VALUE = "__empty__";

type LocalizedConfigCopy = {
	description?: string;
	label: string;
};

const TOOL_CONFIG_COPY_ZH: Record<string, LocalizedConfigCopy> = {
	artifact_list: {
		label: "Artifact 列表",
		description: "列出已保存到制品目录中的文本制品。",
	},
	artifact_read: {
		label: "读取 Artifact",
		description: "按文件名或制品 ID 读取已保存的文本制品。",
	},
	artifact_update: {
		label: "更新 Artifact",
		description: "替换、追加或前置写入已有文本制品。",
	},
	codebase_stats: {
		label: "代码库统计",
		description: "汇总当前工作区的文件数量与代码行数。",
	},
	conversation_summary: {
		label: "对话摘要",
		description: "返回当前线程最近保存的滚动摘要与近期消息。",
	},
	current_utc_time: {
		label: "当前 UTC 时间",
		description: "返回 ISO-8601 格式的当前 UTC 时间戳。",
	},
	git_diff: {
		label: "Git Diff",
		description: "返回当前工作区的 Git diff，也可以限定到指定路径。",
	},
	git_log: {
		label: "Git 日志",
		description: "返回当前仓库最近的提交记录。",
	},
	git_status: {
		label: "Git 状态",
		description: "查看当前仓库的工作区状态。",
	},
	list_files: {
		label: "列出文件",
		description: "按类似 glob 的模式列出工作区目录下的文件。",
	},
	memory_forget: {
		label: "删除记忆",
		description: "从指定或默认命名空间删除一条持久记忆。",
	},
	memory_save: {
		label: "保存记忆",
		description: "保存明确的持久记忆，例如用户偏好或项目事实。",
	},
	memory_search: {
		label: "搜索记忆",
		description: "在默认记忆命名空间中按查询搜索持久记忆。",
	},
	notes_create: {
		label: "创建笔记",
		description: "为当前用户创建一条个人笔记。",
	},
	notes_search: {
		label: "搜索笔记",
		description: "搜索当前用户拥有的个人笔记。",
	},
	notes_update: {
		label: "更新笔记",
		description: "更新当前用户拥有的一条个人笔记。",
	},
	productivity_capture: {
		label: "捕获生产力事项",
		description: "将对话或 Agent Team 内容捕获为明确的笔记或任务。",
	},
	read_file: {
		label: "读取文件",
		description: "读取工作区内 UTF-8 文本文件，并返回带行号内容。",
	},
	search_code: {
		label: "搜索代码",
		description: "在工作区文件中搜索匹配文本并返回匹配行。",
	},
	skill_install: {
		label: "安装 Skill",
		description: "安装可信本地 Skill，或对外部来源返回需审查结果。",
	},
	skill_sources: {
		label: "Skill 来源",
		description: "列出已配置的 Skill 来源及其信任信息。",
	},
	skill_view: {
		label: "查看 Skill",
		description: "加载指定 Skill 的完整说明。",
	},
	skills_list: {
		label: "Skill 列表",
		description: "列出内置和本地 Skill 及其说明和触发前缀。",
	},
	skills_refresh_index: {
		label: "刷新 Skill 索引",
		description: "在项目或来源变更后刷新运行时 Skill 索引。",
	},
	skills_search: {
		label: "搜索 Skill",
		description: "搜索已安装和已配置来源中的相关能力。",
	},
	tasks_create: {
		label: "创建任务",
		description: "为当前用户创建一条个人任务。",
	},
	tasks_list: {
		label: "列出任务",
		description: "列出当前用户拥有的个人任务。",
	},
	tasks_update: {
		label: "更新任务",
		description: "更新当前用户拥有的一条个人任务。",
	},
	web_fetch: {
		label: "抓取网页",
		description: "抓取用户提供的 HTTP 或 HTTPS URL，并提取可读文本。",
	},
	web_search: {
		label: "网页搜索",
		description: "搜索实时网页，优先使用 Tavily，失败时使用 DuckDuckGo。",
	},
	write_text_artifact: {
		label: "写入文本 Artifact",
		description: "将文本制品写入磁盘并返回其位置。",
	},
};

const CONFIG_VALUE_COPY_ZH: Record<string, LocalizedConfigCopy> = {
	agent_artifact_synthesis_enabled: {
		label: "Artifact 合成",
		description: "启用从 Agent Team 工作中合成 Artifact。",
	},
	agent_branch_decision_conclude_threshold: {
		label: "结论阈值",
		description: "触发 conclude 决策所需的置信度阈值。",
	},
	agent_branch_decision_enabled: {
		label: "分支决策",
		description: "启用证据优先的分支决策记录。",
	},
	agent_branch_decision_merge_candidate_threshold: {
		label: "合并候选阈值",
		description: "触发 merge-candidate 决策所需的置信度阈值。",
	},
	agent_branch_decision_min_confidence: {
		label: "分支最低置信度",
		description: "分支决策所需的最低置信度。",
	},
	agent_branch_decision_mode: {
		label: "分支决策模式",
		description: "控制分支决策的执行方式。",
	},
	agent_branch_decision_rate_limit_per_hour: {
		label: "分支决策限速",
		description: "每小时允许的自动分支决策上限。",
	},
	agent_branch_decision_split_threshold: {
		label: "拆分阈值",
		description: "触发 split 决策所需的置信度阈值。",
	},
	agent_branch_recommendation_enabled: {
		label: "分支推荐",
		description: "在每轮对话前启用分支推荐。",
	},
	agent_branch_recommendation_min_confidence: {
		label: "推荐最低置信度",
		description: "触发分支推荐所需的最低置信度。",
	},
	agent_branch_recommendation_mode: {
		label: "分支推荐模式",
		description: "控制分支推荐的展示或执行方式。",
	},
	agent_context_artifact_min_chars: {
		label: "Artifact 最小字符数",
		description: "观测内容达到该长度后才允许转为 Artifact。",
	},
	agent_context_artifactize_long_observations: {
		label: "长观测转 Artifact",
		description: "组装上下文时，将较长的工具观测移动到 Artifact。",
	},
	agent_context_engineering_v2_enabled: {
		label: "上下文工程 v2",
		description: "启用 v2 上下文组装策略面。",
	},
	agent_context_role_views_enabled: {
		label: "角色上下文视图",
		description: "为不同角色组装专属上下文视图。",
	},
	agent_context_tokenizer_mode: {
		label: "上下文 tokenizer 模式",
		description: "用于上下文预算的 tokenizer 策略。",
	},
	agent_critic_gate_enabled: {
		label: "Critic Gate",
		description: "启用 critic gate 评估。",
	},
	agent_critic_gate_enforce: {
		label: "强制 Critic Gate",
		description: "最终输出前必须通过 critic gate 审批。",
	},
	agent_delegation_enabled: {
		label: "任务委派",
		description: "启用 Agent 委派规划。",
	},
	agent_delegation_enforce: {
		label: "强制委派策略",
		description: "要求委派策略给出决策，而不是仅观测。",
	},
	agent_delegation_execution_mode: {
		label: "委派执行模式",
		description: "委派任务使用的执行模式。",
	},
	agent_memory_auto_promote_on_merge: {
		label: "合并后自动提升记忆",
		description: "接受合并后自动提升记忆候选。",
	},
	agent_memory_curator_enabled: {
		label: "记忆整理器",
		description: "启用记忆整理策略。",
	},
	agent_model_router_enabled: {
		label: "模型路由器",
		description: "启用策略辅助的模型选择。",
	},
	agent_model_router_mode: {
		label: "模型路由模式",
		description: "观测或强制执行模型路由决策。",
	},
	agent_role_max_parallel_runs: {
		label: "角色最大并发",
		description: "角色专属模型调用的最大并发数量。",
	},
	agent_role_routing_enabled: {
		label: "角色路由",
		description: "按 planner、executor、critic、memory、skill 等角色路由工作。",
	},
	agent_task_ledger_enabled: {
		label: "任务账本",
		description: "启用任务账本规划与运行追踪。",
	},
	agent_tool_router_enabled: {
		label: "工具路由器",
		description: "启用策略辅助的工具调用路由。",
	},
	agent_tool_router_enforce: {
		label: "强制工具路由",
		description: "阻止被路由器拒绝的工具调用，而不是仅观测。",
	},
	api_host: {
		label: "API 监听地址",
		description: "API 绑定主机，修改后需要重启。",
	},
	api_port: {
		label: "API 端口",
		description: "API 绑定端口，修改后需要重启。",
	},
	auth_jwt_secret: {
		label: "JWT 密钥",
		description: "JWT 签名密钥，页面不会返回具体值。",
	},
	context_auto_compaction_enabled: {
		label: "自动压缩上下文",
		description: "上下文接近预算上限时自动压缩。",
	},
	context_auto_compaction_post_turn_ratio: {
		label: "轮后压缩比例",
		description: "一轮结束后触发上下文压缩的使用比例。",
	},
	context_auto_compaction_pre_send_ratio: {
		label: "发送前压缩比例",
		description: "模型调用前触发上下文压缩的使用比例。",
	},
	database_uri: {
		label: "数据库 URI",
		description: "数据库连接字符串，页面不会返回具体值。",
	},
	metrics_cache_ttl_seconds: {
		label: "指标缓存 TTL",
		description: "指标缓存条目过期前保留的秒数。",
	},
	multi_agent_async_approval_enabled: {
		label: "异步审批",
		description: "允许多 Agent 审批等待异步运行。",
	},
	multi_agent_dag_scheduler_enabled: {
		label: "DAG 调度器",
		description: "启用具备依赖感知的多 Agent 任务调度。",
	},
	multi_agent_failure_handler_enabled: {
		label: "失败恢复协调器",
		description: "启用多 Agent 失败恢复协调能力。",
	},
	multi_agent_message_bus_enabled: {
		label: "消息总线",
		description: "启用结构化 Agent 间消息。",
	},
	multi_agent_resource_lock_enabled: {
		label: "资源锁",
		description: "通过资源锁协调 Agent 的写入归属。",
	},
	multi_agent_v2_enabled: {
		label: "多 Agent v2",
		description: "启用 v2 多 Agent 协同能力面。",
	},
	rate_limit_chat_per_minute: {
		label: "聊天限流",
		description: "每分钟允许的聊天请求数量。",
	},
	rate_limit_enabled: {
		label: "请求限流",
		description: "启用 API 请求限流。",
	},
	rate_limit_per_minute: {
		label: "API 限流",
		description: "每分钟默认 API 请求上限。",
	},
	sse_heartbeat_seconds: {
		label: "SSE 心跳",
		description: "Server-Sent Events 心跳间隔。",
	},
	temperature: {
		label: "Temperature",
		description: "默认聊天模型 temperature。",
	},
	trajectory_enabled: {
		label: "Trajectory 记录",
		description: "存储可用时启用 trajectory 记录。",
	},
};

const CONFIG_OPTION_COPY_ZH: Record<string, string> = {
	background: "后台执行",
	chars_fallback: "字符数兜底",
	enforce: "强制执行",
	execute: "直接执行",
	fake: "模拟执行",
	inline: "内联执行",
	observe: "仅观测",
	shadow: "影子模式",
	suggest: "只推荐",
	tokenizer_first: "优先 tokenizer",
};

function textValue(value: string | null | undefined) {
	return value ?? "";
}

export function nullableText(value: string) {
	const trimmed = value.trim();
	return trimmed ? trimmed : null;
}

export function splitList(value: string) {
	return value
		.split(/[\n,]/)
		.map((item) => item.trim())
		.filter(Boolean);
}

export function uniqueList(values: Array<string | null | undefined>) {
	return Array.from(
		new Set(
			values
				.map((value) => value?.trim() ?? "")
				.filter((value) => value.length > 0),
		),
	);
}

export function localizedToolCopy(
	tool: Pick<ToolEntryDraft, "description" | "label" | "name">,
	isChineseUi: boolean,
) {
	const fallbackLabel = tool.label || tool.name;
	const fallbackDescription = tool.description;
	if (!isChineseUi) {
		return {
			description: fallbackDescription,
			label: fallbackLabel,
		};
	}
	const localized = TOOL_CONFIG_COPY_ZH[tool.name];
	return {
		description: localized?.description ?? fallbackDescription,
		label: localized?.label ?? fallbackLabel,
	};
}

export function localizedConfigValueCopy(
	item: FocusAgentAdminConfigValue,
	isChineseUi: boolean,
) {
	if (!isChineseUi) {
		return {
			description: item.description ?? "",
			label: item.label,
		};
	}
	const localized = CONFIG_VALUE_COPY_ZH[item.key];
	return {
		description: localized?.description ?? item.description ?? "",
		label: localized?.label ?? item.label,
	};
}

export function localizedConfigOptionLabel(
	option: string,
	isChineseUi: boolean,
) {
	if (!isChineseUi) return option;
	return CONFIG_OPTION_COPY_ZH[option] ?? option;
}

export function unknownToText(value: unknown) {
	if (value === null || value === undefined) return "";
	if (typeof value === "string") return value;
	if (typeof value === "number" || typeof value === "boolean") {
		return String(value);
	}
	return JSON.stringify(value);
}

function unknownToBoolean(value: unknown) {
	if (typeof value === "boolean") return value;
	if (typeof value === "string") return value.toLowerCase() === "true";
	return Boolean(value);
}

function providerToDraft(
	provider: FocusAgentAdminConfigProvider,
): ModelProviderDraft {
	return {
		id: provider.id,
		label: textValue(provider.label),
		backendProvider: textValue(provider.backend_provider),
		aliases: provider.aliases.join(", "),
		logoSlug: textValue(provider.logo_slug),
		logoLetter: textValue(provider.logo_letter),
		baseUrlEnv: textValue(provider.base_url_env),
		baseUrlDefault: textValue(provider.base_url_default),
		baseUrlConfigured: provider.base_url_configured,
		apiKeyEnv: textValue(provider.api_key_env),
		apiKeyConfigured: provider.api_key_configured,
	};
}

function modelToDraft(model: FocusAgentAdminModelConfigEntry): ModelEntryDraft {
	return {
		id: model.id,
		label: textValue(model.label),
		supportsThinking: Boolean(model.supports_thinking),
		defaultThinkingEnabled: Boolean(model.default_thinking_enabled),
		reasoningEffort: textValue(model.reasoning_effort),
		noTemperature: Boolean(model.no_temperature),
		original: model,
	};
}

export function buildModelDraft(
	config: FocusAgentAdminConfig | undefined,
): ModelDraft {
	const modelConfig = config?.models;
	return {
		reason: "",
		defaultModel: modelConfig?.default_model ?? "",
		helperModel: modelConfig?.helper_model ?? "",
		modelChoices: [...(modelConfig?.model_choices ?? [])],
		providers: (modelConfig?.providers ?? []).map(providerToDraft),
		models: (modelConfig?.models ?? []).map(modelToDraft),
	};
}

function toolToDraft(tool: FocusAgentAdminToolConfigEntry): ToolEntryDraft {
	return {
		name: tool.name,
		enabled: tool.enabled,
		label: tool.label,
		description: tool.description,
		original: tool,
	};
}

function toolProviderToDraft(
	provider: FocusAgentAdminToolProviderConfig,
): ToolProviderDraft {
	return {
		id: provider.id,
		enabled: provider.enabled,
		order:
			provider.order === null || provider.order === undefined
				? ""
				: String(provider.order),
		overrides: provider.overrides.join(", "),
		metadata: provider.metadata,
	};
}

export function buildToolDraft(
	config: FocusAgentAdminConfig | undefined,
): ToolDraft {
	const toolConfig = config?.tools;
	return {
		reason: "",
		tools: (toolConfig?.tools ?? []).map(toolToDraft),
		providers: (toolConfig?.providers ?? []).map(toolProviderToDraft),
	};
}

export function policyDraftValue(
	item: FocusAgentAdminConfigValue,
): PolicyDraftValue {
	if (item.value_type === "boolean") return unknownToBoolean(item.value);
	return unknownToText(item.value);
}

export function buildPolicyDraft(
	config: FocusAgentAdminConfig | undefined,
): PolicyDraft {
	return {
		reason: "",
		values: Object.fromEntries(
			(config?.policies.items ?? [])
				.filter((item) => item.editable)
				.map((item) => [item.key, policyDraftValue(item)]),
		),
	};
}

export function emptyModelProviderDraft(): ModelProviderDraft {
	return {
		id: "",
		label: "",
		backendProvider: "",
		aliases: "",
		logoSlug: "",
		logoLetter: "",
		baseUrlEnv: "",
		baseUrlDefault: "",
		baseUrlConfigured: false,
		apiKeyEnv: "",
		apiKeyConfigured: false,
	};
}

export function emptyToolProviderDraft(): ToolProviderDraft {
	return {
		id: "",
		enabled: true,
		order: "",
		overrides: "",
		metadata: {},
	};
}

export function coercePolicyValue(
	item: FocusAgentAdminConfigValue,
	value: PolicyDraftValue,
	isChineseUi: boolean,
) {
	if (item.value_type === "boolean") return Boolean(value);
	const text = String(value ?? "").trim();
	if (item.value_type === "integer") {
		const parsed = Number.parseInt(text, 10);
		if (Number.isNaN(parsed)) {
			throw new Error(
				isChineseUi
					? `${item.label} 必须是整数。`
					: `${item.label} must be an integer.`,
			);
		}
		return parsed;
	}
	if (item.value_type === "float") {
		const parsed = Number.parseFloat(text);
		if (Number.isNaN(parsed)) {
			throw new Error(
				isChineseUi
					? `${item.label} 必须是数字。`
					: `${item.label} must be a number.`,
			);
		}
		return parsed;
	}
	return text;
}
