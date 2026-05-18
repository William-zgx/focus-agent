import type {
	FocusAgentAdminConfig,
	FocusAgentAdminConfigProvider,
	FocusAgentAdminConfigValue,
	FocusAgentAdminModelConfigEntry,
	FocusAgentAdminToolConfigEntry,
	FocusAgentAdminToolProviderConfig,
	FocusAgentUpdateAdminModelConfigEntry,
	FocusAgentUpdateAdminModelConfigRequest,
	FocusAgentUpdateAdminModelProviderConfig,
	FocusAgentUpdateAdminToolConfigEntry,
	FocusAgentUpdateAdminToolConfigRequest,
	FocusAgentUpdateAdminToolProviderConfig,
} from "@focus-agent/web-sdk";
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
	useAdminConfig,
	useUpdateAdminModelConfig,
	useUpdateAdminPolicyConfig,
	useUpdateAdminToolConfig,
} from "@/features/admin-config/use-admin-config";

import { AdminConsoleLayout, AdminErrorMessage } from "./admin-page-chrome";
import { AdminField, AdminPanelHeader } from "./admin-page-sections";

type EditableConfigSection = "models" | "policies" | "tools";
type ConfigSection = EditableConfigSection | "system";
type PolicyDraftValue = boolean | string;

type ModelProviderDraft = {
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

type ModelEntryDraft = {
	id: string;
	label: string;
	supportsThinking: boolean;
	defaultThinkingEnabled: boolean;
	reasoningEffort: string;
	noTemperature: boolean;
	original: FocusAgentAdminModelConfigEntry;
};

type ModelDraft = {
	reason: string;
	defaultModel: string;
	helperModel: string;
	modelChoices: string[];
	providers: ModelProviderDraft[];
	models: ModelEntryDraft[];
};

type ToolEntryDraft = {
	name: string;
	enabled: boolean;
	label: string;
	description: string;
	original: FocusAgentAdminToolConfigEntry;
};

type ToolProviderDraft = {
	id: string;
	enabled: boolean;
	order: string;
	overrides: string;
	metadata: Record<string, unknown>;
};

type ToolDraft = {
	reason: string;
	tools: ToolEntryDraft[];
	providers: ToolProviderDraft[];
};

type PolicyDraft = {
	reason: string;
	values: Record<string, PolicyDraftValue>;
};

const EMPTY_SELECT_VALUE = "__empty__";

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

function nullableText(value: string) {
	const trimmed = value.trim();
	return trimmed ? trimmed : null;
}

function splitList(value: string) {
	return value
		.split(/[\n,]/)
		.map((item) => item.trim())
		.filter(Boolean);
}

function uniqueList(values: Array<string | null | undefined>) {
	return Array.from(
		new Set(
			values
				.map((value) => value?.trim() ?? "")
				.filter((value) => value.length > 0),
		),
	);
}

function localizedToolCopy(
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

function localizedConfigValueCopy(
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

function localizedConfigOptionLabel(option: string, isChineseUi: boolean) {
	if (!isChineseUi) return option;
	return CONFIG_OPTION_COPY_ZH[option] ?? option;
}

function unknownToText(value: unknown) {
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

function buildModelDraft(
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

function buildToolDraft(config: FocusAgentAdminConfig | undefined): ToolDraft {
	const toolConfig = config?.tools;
	return {
		reason: "",
		tools: (toolConfig?.tools ?? []).map(toolToDraft),
		providers: (toolConfig?.providers ?? []).map(toolProviderToDraft),
	};
}

function policyDraftValue(item: FocusAgentAdminConfigValue): PolicyDraftValue {
	if (item.value_type === "boolean") return unknownToBoolean(item.value);
	return unknownToText(item.value);
}

function buildPolicyDraft(
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

function emptyModelProviderDraft(): ModelProviderDraft {
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

function emptyToolProviderDraft(): ToolProviderDraft {
	return {
		id: "",
		enabled: true,
		order: "",
		overrides: "",
		metadata: {},
	};
}

function coercePolicyValue(
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

export function AdminConfigPage() {
	const { isChineseUi } = useShellUi();
	const locale = isChineseUi ? "zh-CN" : "en-US";
	const configQuery = useAdminConfig();
	const modelMutation = useUpdateAdminModelConfig();
	const toolMutation = useUpdateAdminToolConfig();
	const policyMutation = useUpdateAdminPolicyConfig();
	const [modelDraft, setModelDraft] = useState<ModelDraft>(() =>
		buildModelDraft(undefined),
	);
	const [toolDraft, setToolDraft] = useState<ToolDraft>(() =>
		buildToolDraft(undefined),
	);
	const [policyDraft, setPolicyDraft] = useState<PolicyDraft>(() =>
		buildPolicyDraft(undefined),
	);
	const [activeConfigSection, setActiveConfigSection] =
		useState<ConfigSection>("models");
	const [formError, setFormError] = useState("");
	const config = configQuery.data;
	const editablePolicyItems = useMemo(
		() => (config?.policies.items ?? []).filter((item) => item.editable),
		[config?.policies.items],
	);
	const pendingSection: EditableConfigSection | null = modelMutation.isPending
		? "models"
		: toolMutation.isPending
			? "tools"
			: policyMutation.isPending
				? "policies"
				: null;
	const summary = useMemo(
		() => ({
			defaultModel: config?.models?.default_model || "-",
			modelCount: config?.models?.models?.length ?? 0,
			policyCount: config?.policies?.items?.length ?? 0,
			systemCount: config?.system?.items?.length ?? 0,
			toolCount: config?.tools?.tools?.length ?? 0,
			toolProviderCount: config?.tools?.providers?.length ?? 0,
		}),
		[config],
	);

	useEffect(() => {
		if (!config) return;
		setModelDraft(buildModelDraft(config));
		setToolDraft(buildToolDraft(config));
		setPolicyDraft(buildPolicyDraft(config));
		setFormError("");
	}, [config]);

	const modelChoiceOptions = useMemo(
		() =>
			uniqueList([
				modelDraft.defaultModel,
				modelDraft.helperModel,
				...modelDraft.modelChoices,
				...modelDraft.models.map((model) => model.id),
			]),
		[
			modelDraft.defaultModel,
			modelDraft.helperModel,
			modelDraft.modelChoices,
			modelDraft.models,
		],
	);
	const disabled = Boolean(pendingSection);

	function updateModelChoice(modelId: string, checked: boolean) {
		setModelDraft((current) => ({
			...current,
			modelChoices: checked
				? uniqueList([...current.modelChoices, modelId])
				: current.modelChoices.filter((item) => item !== modelId),
		}));
	}

	function updateModelProvider(
		index: number,
		patch: Partial<ModelProviderDraft>,
	) {
		setModelDraft((current) => ({
			...current,
			providers: current.providers.map((provider, providerIndex) =>
				providerIndex === index ? { ...provider, ...patch } : provider,
			),
		}));
	}

	function removeModelProvider(index: number) {
		setModelDraft((current) => ({
			...current,
			providers: current.providers.filter(
				(_, providerIndex) => providerIndex !== index,
			),
		}));
	}

	function updateModelEntry(index: number, patch: Partial<ModelEntryDraft>) {
		setModelDraft((current) => ({
			...current,
			models: current.models.map((model, modelIndex) =>
				modelIndex === index ? { ...model, ...patch } : model,
			),
		}));
	}

	function updateToolEntry(index: number, patch: Partial<ToolEntryDraft>) {
		setToolDraft((current) => ({
			...current,
			tools: current.tools.map((tool, toolIndex) =>
				toolIndex === index ? { ...tool, ...patch } : tool,
			),
		}));
	}

	function updateToolProvider(
		index: number,
		patch: Partial<ToolProviderDraft>,
	) {
		setToolDraft((current) => ({
			...current,
			providers: current.providers.map((provider, providerIndex) =>
				providerIndex === index ? { ...provider, ...patch } : provider,
			),
		}));
	}

	function removeToolProvider(index: number) {
		setToolDraft((current) => ({
			...current,
			providers: current.providers.filter(
				(_, providerIndex) => providerIndex !== index,
			),
		}));
	}

	function updatePolicyValue(key: string, value: PolicyDraftValue) {
		setPolicyDraft((current) => ({
			...current,
			values: { ...current.values, [key]: value },
		}));
	}

	async function handleModelSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setFormError("");
		try {
			const providers: FocusAgentUpdateAdminModelProviderConfig[] =
				modelDraft.providers.map((provider) => {
					const id = provider.id.trim();
					if (!id) {
						throw new Error(
							isChineseUi
								? "Provider ID 不能为空。"
								: "Provider ID is required.",
						);
					}
					return {
						id,
						label: nullableText(provider.label),
						backend_provider: nullableText(provider.backendProvider),
						aliases: splitList(provider.aliases),
						logo_slug: nullableText(provider.logoSlug),
						logo_letter: nullableText(provider.logoLetter),
						base_url_env: nullableText(provider.baseUrlEnv),
						base_url_default: nullableText(provider.baseUrlDefault),
						api_key_env: nullableText(provider.apiKeyEnv),
					};
				});
			const models: FocusAgentUpdateAdminModelConfigEntry[] =
				modelDraft.models.map((model) => {
					const id = model.id.trim();
					if (!id) {
						throw new Error(
							isChineseUi ? "模型 ID 不能为空。" : "Model ID is required.",
						);
					}
					return {
						id,
						label: nullableText(model.label),
						supports_thinking: model.supportsThinking,
						default_thinking_enabled: model.supportsThinking
							? model.defaultThinkingEnabled
							: false,
						request_kwargs: model.original.request_kwargs,
						thinking_enabled_request_kwargs:
							model.original.thinking_enabled_request_kwargs,
						thinking_disabled_request_kwargs:
							model.original.thinking_disabled_request_kwargs,
						thinking_disabled_model_name:
							model.original.thinking_disabled_model_name,
						reasoning_effort: nullableText(model.reasoningEffort),
						no_temperature: model.noTemperature,
						thinking_enable_extra_body_type:
							model.original.thinking_enable_extra_body_type,
						thinking_disable_extra_body_type:
							model.original.thinking_disable_extra_body_type,
						thinking_disable_switch_model:
							model.original.thinking_disable_switch_model,
					};
				});
			const request: FocusAgentUpdateAdminModelConfigRequest = {
				reason: nullableText(modelDraft.reason),
				default_model: nullableText(modelDraft.defaultModel),
				helper_model: nullableText(modelDraft.helperModel),
				model_choices: uniqueList(modelDraft.modelChoices),
				providers,
				models,
			};
			await modelMutation.mutateAsync(request);
		} catch (error) {
			setFormError(
				error instanceof Error
					? error.message
					: isChineseUi
						? "保存模型配置失败。"
						: "Failed to save model config.",
			);
		}
	}

	async function handleToolSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setFormError("");
		try {
			const tools: FocusAgentUpdateAdminToolConfigEntry[] = toolDraft.tools.map(
				(tool) => ({
					name: tool.name,
					enabled: tool.enabled,
					label: nullableText(tool.label),
					description: nullableText(tool.description),
					settings: tool.original.settings,
					metadata: tool.original.metadata,
				}),
			);
			const providers: FocusAgentUpdateAdminToolProviderConfig[] =
				toolDraft.providers.map((provider) => {
					const id = provider.id.trim();
					if (!id) {
						throw new Error(
							isChineseUi
								? "工具 Provider ID 不能为空。"
								: "Tool provider ID is required.",
						);
					}
					const order =
						provider.order.trim().length === 0
							? null
							: Number.parseInt(provider.order, 10);
					if (Number.isNaN(order)) {
						throw new Error(
							isChineseUi
								? `${provider.id} 的顺序必须是整数。`
								: `${provider.id} order must be an integer.`,
						);
					}
					return {
						id,
						enabled: provider.enabled,
						order,
						metadata: provider.metadata,
						overrides: splitList(provider.overrides),
					};
				});
			const request: FocusAgentUpdateAdminToolConfigRequest = {
				reason: nullableText(toolDraft.reason),
				tools,
				providers,
			};
			await toolMutation.mutateAsync(request);
		} catch (error) {
			setFormError(
				error instanceof Error
					? error.message
					: isChineseUi
						? "保存工具配置失败。"
						: "Failed to save tool config.",
			);
		}
	}

	async function handlePolicySubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setFormError("");
		try {
			const values = Object.fromEntries(
				editablePolicyItems.map((item) => [
					item.key,
					coercePolicyValue(
						item,
						policyDraft.values[item.key] ?? "",
						isChineseUi,
					),
				]),
			);
			await policyMutation.mutateAsync({
				reason: nullableText(policyDraft.reason),
				values,
			});
		} catch (error) {
			setFormError(
				error instanceof Error
					? error.message
					: isChineseUi
						? "保存策略配置失败。"
						: "Failed to save policy config.",
			);
		}
	}

	return (
		<AdminConsoleLayout
			active="config"
			title={isChineseUi ? "配置中心" : "Config Center"}
			summary={
				isChineseUi
					? "集中查看和更新模型、工具与策略配置。"
					: "Review and update model, tool, and policy configuration."
			}
			toolbar={
				<button
					className="fa-observability-preset"
					type="button"
					onClick={() => void configQuery.refetch()}
				>
					{isChineseUi ? "重新加载" : "Reload"}
				</button>
			}
		>
			<section
				aria-label={isChineseUi ? "配置项选择" : "Config section picker"}
				className="fa-admin-config-switchboard"
			>
				<ConfigSectionPicker
					active={activeConfigSection}
					isChineseUi={isChineseUi}
					onChange={setActiveConfigSection}
					summary={summary}
				/>
				{configQuery.error ? (
					<AdminErrorMessage
						error={configQuery.error}
						fallback="Failed to load admin config."
					/>
				) : null}
				{formError ? (
					<div className="fa-inline-notice is-danger">{formError}</div>
				) : null}
			</section>

			<div className="fa-admin-config-detail">
				{activeConfigSection === "models" ? (
					<ModelConfigPanel
						choiceOptions={modelChoiceOptions}
						disabled={disabled}
						draft={modelDraft}
						isChineseUi={isChineseUi}
						onAddProvider={() =>
							setModelDraft((current) => ({
								...current,
								providers: [...current.providers, emptyModelProviderDraft()],
							}))
						}
						onChange={setModelDraft}
						onChoiceChange={updateModelChoice}
						onEntryChange={updateModelEntry}
						onProviderChange={updateModelProvider}
						onProviderRemove={removeModelProvider}
						onReset={() => setModelDraft(buildModelDraft(config))}
						onSubmit={(event) => void handleModelSubmit(event)}
						pending={pendingSection === "models"}
						source={config?.models.source}
					/>
				) : null}
				{activeConfigSection === "tools" ? (
					<ToolConfigPanel
						disabled={disabled}
						draft={toolDraft}
						isChineseUi={isChineseUi}
						onAddProvider={() =>
							setToolDraft((current) => ({
								...current,
								providers: [...current.providers, emptyToolProviderDraft()],
							}))
						}
						onChange={setToolDraft}
						onProviderChange={updateToolProvider}
						onProviderRemove={removeToolProvider}
						onReset={() => setToolDraft(buildToolDraft(config))}
						onSubmit={(event) => void handleToolSubmit(event)}
						onToolChange={updateToolEntry}
						pending={pendingSection === "tools"}
						source={config?.tools.source}
					/>
				) : null}
				{activeConfigSection === "policies" ? (
					<PolicyConfigPanel
						disabled={disabled}
						draft={policyDraft}
						isChineseUi={isChineseUi}
						items={editablePolicyItems}
						onChange={setPolicyDraft}
						onReset={() => setPolicyDraft(buildPolicyDraft(config))}
						onSubmit={(event) => void handlePolicySubmit(event)}
						onValueChange={updatePolicyValue}
						pending={pendingSection === "policies"}
						source={config?.policies.source}
					/>
				) : null}
				{activeConfigSection === "system" ? (
					<SystemConfigPanel
						isChineseUi={isChineseUi}
						items={config?.system.items ?? []}
						source={config?.system.source}
					/>
				) : null}
			</div>
		</AdminConsoleLayout>
	);
}

function ConfigSectionPicker({
	active,
	isChineseUi,
	onChange,
	summary,
}: {
	active: ConfigSection;
	isChineseUi: boolean;
	onChange: (section: ConfigSection) => void;
	summary: {
		defaultModel: string;
		modelCount: number;
		policyCount: number;
		systemCount: number;
		toolCount: number;
		toolProviderCount: number;
	};
}) {
	const options: Array<{
		ariaLabel: string;
		key: ConfigSection;
		description: string;
		label: string;
		metric: string;
	}> = [
		{
			key: "models",
			label: isChineseUi ? "模型" : "Models",
			metric: String(summary.modelCount),
			description: isChineseUi
				? "默认模型、助手模型与模型提供方"
				: "Default model, assistant model, and providers.",
			ariaLabel: isChineseUi
				? `默认 ${summary.defaultModel}`
				: `Default ${summary.defaultModel}`,
		},
		{
			key: "tools",
			label: isChineseUi ? "工具" : "Tools",
			metric: `${summary.toolCount} / ${summary.toolProviderCount}`,
			description: isChineseUi
				? "工具能力、可用列表与 Provider"
				: "Tool capabilities, catalog, and providers",
			ariaLabel: isChineseUi ? "工具与 Provider" : "Tools and providers",
		},
		{
			key: "policies",
			label: isChineseUi ? "策略" : "Policies",
			metric: String(summary.policyCount),
			description: isChineseUi
				? "分支推荐策略与路由治理规则"
				: "Branch recommendation and routing policies",
			ariaLabel: isChineseUi
				? "分支推荐、路由与治理"
				: "Branching, routing, and governance",
		},
		{
			key: "system",
			label: isChineseUi ? "系统" : "System",
			metric: String(summary.systemCount),
			description: isChineseUi
				? "运行环境、审计与敏感配置"
				: "Runtime, audit, and secrets",
			ariaLabel: isChineseUi ? "运行环境与敏感项" : "Runtime and secrets",
		},
	];

	return (
		<div className="fa-admin-config-section-picker" role="tablist">
			{options.map((option) => (
				<button
					aria-label={`${option.label}: ${option.ariaLabel}`}
					aria-selected={active === option.key}
					className={`fa-admin-config-section-option ${
						active === option.key ? "is-active" : ""
					}`.trim()}
					key={option.key}
					role="tab"
					type="button"
					onClick={() => onChange(option.key)}
				>
					<span>{option.label}</span>
					<strong>{option.metric}</strong>
					<small>{option.description}</small>
				</button>
			))}
		</div>
	);
}

function ModelConfigPanel({
	choiceOptions,
	disabled,
	draft,
	isChineseUi,
	onAddProvider,
	onChange,
	onChoiceChange,
	onEntryChange,
	onProviderChange,
	onProviderRemove,
	onReset,
	onSubmit,
	pending,
	source,
}: {
	choiceOptions: string[];
	disabled: boolean;
	draft: ModelDraft;
	isChineseUi: boolean;
	onAddProvider: () => void;
	onChange: (draft: ModelDraft) => void;
	onChoiceChange: (modelId: string, checked: boolean) => void;
	onEntryChange: (index: number, patch: Partial<ModelEntryDraft>) => void;
	onProviderChange: (index: number, patch: Partial<ModelProviderDraft>) => void;
	onProviderRemove: (index: number) => void;
	onReset: () => void;
	onSubmit: (event: FormEvent<HTMLFormElement>) => void;
	pending: boolean;
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	return (
		<form
			className="fa-admin-panel fa-admin-config-panel is-wide"
			onSubmit={onSubmit}
		>
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Models" : "Models"}
				status={pending ? (isChineseUi ? "保存中" : "saving") : null}
				title={isChineseUi ? "模型配置" : "Model Config"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "选择默认模型、助手模型、可用模型池，并维护多个 Provider。"
					: "Choose default/helper models, selectable model choices, and multiple providers."}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-form-grid is-two">
				<AdminField label={isChineseUi ? "默认模型" : "Default model"}>
					<select
						disabled={disabled}
						value={draft.defaultModel || EMPTY_SELECT_VALUE}
						onChange={(event) => {
							const value =
								event.target.value === EMPTY_SELECT_VALUE
									? ""
									: event.target.value;
							onChange({
								...draft,
								defaultModel: value,
								modelChoices: value
									? uniqueList([...draft.modelChoices, value])
									: draft.modelChoices,
							});
						}}
					>
						<option value={EMPTY_SELECT_VALUE}>
							{isChineseUi ? "未设置" : "Not set"}
						</option>
						{choiceOptions.map((modelId) => (
							<option key={modelId} value={modelId}>
								{modelId}
							</option>
						))}
					</select>
				</AdminField>
				<AdminField label={isChineseUi ? "助手模型" : "Helper model"}>
					<select
						disabled={disabled}
						value={draft.helperModel || EMPTY_SELECT_VALUE}
						onChange={(event) => {
							const value =
								event.target.value === EMPTY_SELECT_VALUE
									? ""
									: event.target.value;
							onChange({
								...draft,
								helperModel: value,
								modelChoices: value
									? uniqueList([...draft.modelChoices, value])
									: draft.modelChoices,
							});
						}}
					>
						<option value={EMPTY_SELECT_VALUE}>
							{isChineseUi ? "未设置" : "Not set"}
						</option>
						{choiceOptions.map((modelId) => (
							<option key={modelId} value={modelId}>
								{modelId}
							</option>
						))}
					</select>
				</AdminField>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "可选模型池" : "Model choices"}</strong>
				</div>
				<div className="fa-admin-picker-list">
					{choiceOptions.map((modelId) => (
						<label className="fa-admin-config-choice" key={modelId}>
							<input
								checked={draft.modelChoices.includes(modelId)}
								disabled={disabled}
								type="checkbox"
								onChange={(event) =>
									onChoiceChange(modelId, event.target.checked)
								}
							/>
							<span>{modelId}</span>
						</label>
					))}
				</div>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "模型 Provider" : "Model providers"}</strong>
					<button
						className="fa-observability-preset"
						disabled={disabled}
						type="button"
						onClick={onAddProvider}
					>
						{isChineseUi ? "添加 Provider" : "Add provider"}
					</button>
				</div>
				<div className="fa-admin-config-card-list">
					{draft.providers.map((provider, index) => (
						<div
							className="fa-admin-config-card"
							key={`${provider.id}-${index}`}
						>
							<div className="fa-admin-config-card-head">
								<strong>
									{provider.id ||
										(isChineseUi ? "新 Provider" : "New provider")}
								</strong>
								<div className="fa-admin-chip-row">
									<span>
										{provider.baseUrlConfigured
											? isChineseUi
												? "Base URL 已配置"
												: "Base URL configured"
											: isChineseUi
												? "Base URL 未配置"
												: "Base URL missing"}
									</span>
									<span>
										{provider.apiKeyConfigured
											? isChineseUi
												? "Key 已配置"
												: "Key configured"
											: isChineseUi
												? "Key 未配置"
												: "Key missing"}
									</span>
								</div>
							</div>
							<div className="fa-admin-form-grid is-three">
								<AdminField label="Provider ID">
									<input
										disabled={disabled}
										value={provider.id}
										onChange={(event) =>
											onProviderChange(index, { id: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label={isChineseUi ? "显示名称" : "Label"}>
									<input
										disabled={disabled}
										value={provider.label}
										onChange={(event) =>
											onProviderChange(index, { label: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Backend">
									<input
										disabled={disabled}
										value={provider.backendProvider}
										onChange={(event) =>
											onProviderChange(index, {
												backendProvider: event.target.value,
											})
										}
									/>
								</AdminField>
								<AdminField label="Aliases">
									<input
										disabled={disabled}
										placeholder="openai, azure"
										value={provider.aliases}
										onChange={(event) =>
											onProviderChange(index, { aliases: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Base URL env">
									<input
										disabled={disabled}
										value={provider.baseUrlEnv}
										onChange={(event) =>
											onProviderChange(index, {
												baseUrlEnv: event.target.value,
											})
										}
									/>
								</AdminField>
								<AdminField label="API key env">
									<input
										disabled={disabled}
										value={provider.apiKeyEnv}
										onChange={(event) =>
											onProviderChange(index, { apiKeyEnv: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Base URL default">
									<input
										disabled={disabled}
										value={provider.baseUrlDefault}
										onChange={(event) =>
											onProviderChange(index, {
												baseUrlDefault: event.target.value,
											})
										}
									/>
								</AdminField>
								<AdminField label="Logo slug">
									<input
										disabled={disabled}
										value={provider.logoSlug}
										onChange={(event) =>
											onProviderChange(index, { logoSlug: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Logo letter">
									<input
										disabled={disabled}
										value={provider.logoLetter}
										onChange={(event) =>
											onProviderChange(index, {
												logoLetter: event.target.value,
											})
										}
									/>
								</AdminField>
							</div>
							<button
								className="fa-observability-preset"
								disabled={disabled}
								type="button"
								onClick={() => onProviderRemove(index)}
							>
								{isChineseUi ? "移除 Provider" : "Remove provider"}
							</button>
						</div>
					))}
				</div>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "模型条目" : "Model entries"}</strong>
				</div>
				<div className="fa-admin-config-card-list">
					{draft.models.map((model, index) => (
						<div className="fa-admin-config-card" key={`${model.id}-${index}`}>
							<div className="fa-admin-form-grid is-three">
								<AdminField label="Model ID">
									<input
										disabled={disabled}
										value={model.id}
										onChange={(event) =>
											onEntryChange(index, { id: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label={isChineseUi ? "显示名称" : "Label"}>
									<input
										disabled={disabled}
										value={model.label}
										onChange={(event) =>
											onEntryChange(index, { label: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Reasoning effort">
									<input
										disabled={disabled}
										value={model.reasoningEffort}
										onChange={(event) =>
											onEntryChange(index, {
												reasoningEffort: event.target.value,
											})
										}
									/>
								</AdminField>
							</div>
							<div className="fa-admin-picker-list">
								<ToggleControl
									checked={model.supportsThinking}
									disabled={disabled}
									label={isChineseUi ? "支持 Thinking" : "Supports thinking"}
									onChange={(checked) =>
										onEntryChange(index, { supportsThinking: checked })
									}
								/>
								<ToggleControl
									checked={model.defaultThinkingEnabled}
									disabled={disabled || !model.supportsThinking}
									label={
										isChineseUi ? "默认开启 Thinking" : "Thinking on by default"
									}
									onChange={(checked) =>
										onEntryChange(index, {
											defaultThinkingEnabled: checked,
										})
									}
								/>
								<ToggleControl
									checked={model.noTemperature}
									disabled={disabled}
									label={isChineseUi ? "不发送 temperature" : "No temperature"}
									onChange={(checked) =>
										onEntryChange(index, { noTemperature: checked })
									}
								/>
							</div>
						</div>
					))}
				</div>
			</div>
			<AdminField label={isChineseUi ? "变更原因" : "Change reason"}>
				<input
					disabled={disabled}
					value={draft.reason}
					onChange={(event) =>
						onChange({ ...draft, reason: event.target.value })
					}
				/>
			</AdminField>
			<ConfigActions
				disabled={disabled}
				isChineseUi={isChineseUi}
				onReset={onReset}
				pending={pending}
			/>
		</form>
	);
}

function ToolConfigPanel({
	disabled,
	draft,
	isChineseUi,
	onAddProvider,
	onChange,
	onProviderChange,
	onProviderRemove,
	onReset,
	onSubmit,
	onToolChange,
	pending,
	source,
}: {
	disabled: boolean;
	draft: ToolDraft;
	isChineseUi: boolean;
	onAddProvider: () => void;
	onChange: (draft: ToolDraft) => void;
	onProviderChange: (index: number, patch: Partial<ToolProviderDraft>) => void;
	onProviderRemove: (index: number) => void;
	onReset: () => void;
	onSubmit: (event: FormEvent<HTMLFormElement>) => void;
	onToolChange: (index: number, patch: Partial<ToolEntryDraft>) => void;
	pending: boolean;
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	return (
		<form className="fa-admin-panel fa-admin-config-panel" onSubmit={onSubmit}>
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Tools" : "Tools"}
				status={pending ? (isChineseUi ? "保存中" : "saving") : null}
				title={isChineseUi ? "工具配置" : "Tool Config"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "开启或关闭工具，调整工具 Provider 的启用状态、顺序和覆盖项。"
					: "Enable tools and tune tool provider state, order, and overrides."}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "工具开关" : "Tool switches"}</strong>
				</div>
				<div className="fa-admin-config-list">
					{draft.tools.map((tool, index) => {
						const copy = localizedToolCopy(tool, isChineseUi);
						return (
							<div className="fa-admin-config-value-row" key={tool.name}>
								<ToggleControl
									checked={tool.enabled}
									disabled={disabled}
									label={copy.label}
									onChange={(checked) =>
										onToolChange(index, { enabled: checked })
									}
								/>
								{copy.description ? <p>{copy.description}</p> : null}
								<div className="fa-admin-form-grid is-two">
									<AdminField label={isChineseUi ? "显示名称" : "Label"}>
										<input
											disabled={disabled}
											value={tool.label}
											onChange={(event) =>
												onToolChange(index, { label: event.target.value })
											}
										/>
									</AdminField>
									<AdminField label={isChineseUi ? "说明" : "Description"}>
										<input
											disabled={disabled}
											value={tool.description}
											onChange={(event) =>
												onToolChange(index, {
													description: event.target.value,
												})
											}
										/>
									</AdminField>
								</div>
							</div>
						);
					})}
				</div>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "工具 Provider" : "Tool providers"}</strong>
					<button
						className="fa-observability-preset"
						disabled={disabled}
						type="button"
						onClick={onAddProvider}
					>
						{isChineseUi ? "添加 Provider" : "Add provider"}
					</button>
				</div>
				<div className="fa-admin-config-card-list">
					{draft.providers.map((provider, index) => (
						<div
							className="fa-admin-config-card"
							key={`${provider.id}-${index}`}
						>
							<div className="fa-admin-config-card-head">
								<ToggleControl
									checked={provider.enabled}
									disabled={disabled}
									label={
										provider.id ||
										(isChineseUi ? "新 Provider" : "New provider")
									}
									onChange={(checked) =>
										onProviderChange(index, { enabled: checked })
									}
								/>
								<button
									className="fa-observability-preset"
									disabled={disabled}
									type="button"
									onClick={() => onProviderRemove(index)}
								>
									{isChineseUi ? "移除" : "Remove"}
								</button>
							</div>
							<div className="fa-admin-form-grid is-three">
								<AdminField label="Provider ID">
									<input
										disabled={disabled}
										value={provider.id}
										onChange={(event) =>
											onProviderChange(index, { id: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label={isChineseUi ? "顺序" : "Order"}>
									<input
										disabled={disabled}
										inputMode="numeric"
										value={provider.order}
										onChange={(event) =>
											onProviderChange(index, { order: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Overrides">
									<input
										disabled={disabled}
										value={provider.overrides}
										onChange={(event) =>
											onProviderChange(index, { overrides: event.target.value })
										}
									/>
								</AdminField>
							</div>
						</div>
					))}
				</div>
			</div>
			<AdminField label={isChineseUi ? "变更原因" : "Change reason"}>
				<input
					disabled={disabled}
					value={draft.reason}
					onChange={(event) =>
						onChange({ ...draft, reason: event.target.value })
					}
				/>
			</AdminField>
			<ConfigActions
				disabled={disabled}
				isChineseUi={isChineseUi}
				onReset={onReset}
				pending={pending}
			/>
		</form>
	);
}

function PolicyConfigPanel({
	disabled,
	draft,
	isChineseUi,
	items,
	onChange,
	onReset,
	onSubmit,
	onValueChange,
	pending,
	source,
}: {
	disabled: boolean;
	draft: PolicyDraft;
	isChineseUi: boolean;
	items: FocusAgentAdminConfigValue[];
	onChange: (draft: PolicyDraft) => void;
	onReset: () => void;
	onSubmit: (event: FormEvent<HTMLFormElement>) => void;
	onValueChange: (key: string, value: PolicyDraftValue) => void;
	pending: boolean;
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	return (
		<form className="fa-admin-panel fa-admin-config-panel" onSubmit={onSubmit}>
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Policies" : "Policies"}
				status={pending ? (isChineseUi ? "保存中" : "saving") : null}
				title={isChineseUi ? "策略配置" : "Policy Config"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "布尔项用开关，枚举项用下拉，数值项直接填写。"
					: "Use switches for booleans, selects for enums, and inputs for numbers."}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-config-list">
				{items.map((item) => {
					const copy = localizedConfigValueCopy(item, isChineseUi);
					return (
						<div className="fa-admin-config-value-row" key={item.key}>
							<PolicyControl
								disabled={disabled}
								isChineseUi={isChineseUi}
								item={item}
								label={copy.label}
								onChange={(value) => onValueChange(item.key, value)}
								value={draft.values[item.key] ?? policyDraftValue(item)}
							/>
							{copy.description ? <p>{copy.description}</p> : null}
						</div>
					);
				})}
			</div>
			<AdminField label={isChineseUi ? "变更原因" : "Change reason"}>
				<input
					disabled={disabled}
					value={draft.reason}
					onChange={(event) =>
						onChange({ ...draft, reason: event.target.value })
					}
				/>
			</AdminField>
			<ConfigActions
				disabled={disabled}
				isChineseUi={isChineseUi}
				onReset={onReset}
				pending={pending}
			/>
		</form>
	);
}

function SystemConfigPanel({
	isChineseUi,
	items,
	source,
}: {
	isChineseUi: boolean;
	items: FocusAgentAdminConfigValue[];
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	return (
		<section className="fa-admin-panel fa-admin-config-panel">
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Readonly" : "Readonly"}
				status={null}
				title={isChineseUi ? "基础配置" : "System Config"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "运行环境与敏感项只读展示；敏感值只显示是否已配置。"
					: "Runtime and secret settings are read-only; secret values show configured state only."}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-config-list">
				{items.map((item) => (
					<ReadOnlyConfigValue
						isChineseUi={isChineseUi}
						item={item}
						key={item.key}
					/>
				))}
			</div>
		</section>
	);
}

function PolicyControl({
	disabled,
	isChineseUi,
	item,
	label,
	onChange,
	value,
}: {
	disabled: boolean;
	isChineseUi: boolean;
	item: FocusAgentAdminConfigValue;
	label: string;
	onChange: (value: PolicyDraftValue) => void;
	value: PolicyDraftValue;
}) {
	if (item.value_type === "boolean") {
		return (
			<ToggleControl
				checked={Boolean(value)}
				disabled={disabled}
				label={label}
				onChange={onChange}
			/>
		);
	}

	if (item.options.length > 0) {
		return (
			<AdminField label={label}>
				<select
					disabled={disabled}
					value={String(value ?? "")}
					onChange={(event) => onChange(event.target.value)}
				>
					{item.options.map((option) => (
						<option key={option} value={option}>
							{localizedConfigOptionLabel(option, isChineseUi)}
						</option>
					))}
				</select>
			</AdminField>
		);
	}

	if (item.value_type === "integer" || item.value_type === "float") {
		return (
			<AdminField label={label}>
				<input
					disabled={disabled}
					inputMode="decimal"
					step={item.value_type === "integer" ? "1" : "any"}
					type="number"
					value={String(value ?? "")}
					onChange={(event) => onChange(event.target.value)}
				/>
			</AdminField>
		);
	}

	return (
		<AdminField label={label}>
			<input
				disabled={disabled}
				value={String(value ?? "")}
				onChange={(event) => onChange(event.target.value)}
			/>
		</AdminField>
	);
}

function ToggleControl({
	checked,
	disabled,
	label,
	onChange,
}: {
	checked: boolean;
	disabled: boolean;
	label: string;
	onChange: (checked: boolean) => void;
}) {
	return (
		<label className="fa-admin-config-switch">
			<input
				checked={checked}
				disabled={disabled}
				type="checkbox"
				onChange={(event) => onChange(event.target.checked)}
			/>
			<span>{label}</span>
		</label>
	);
}

function ConfigSourceMeta({
	isChineseUi,
	source,
}: {
	isChineseUi: boolean;
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	if (!source) return null;
	return (
		<div className="fa-admin-config-source">
			<span>{source.path}</span>
			<strong>
				{source.exists ? (isChineseUi ? "存在" : "exists") : "new"}
			</strong>
			<strong>
				{source.writable
					? isChineseUi
						? "可写"
						: "writable"
					: isChineseUi
						? "只读"
						: "read-only"}
			</strong>
		</div>
	);
}

function ConfigActions({
	disabled,
	isChineseUi,
	onReset,
	pending,
}: {
	disabled: boolean;
	isChineseUi: boolean;
	onReset: () => void;
	pending: boolean;
}) {
	return (
		<div className="fa-admin-action-row">
			<button
				className="fa-observability-preset is-primary"
				disabled={disabled}
				type="submit"
			>
				{pending
					? isChineseUi
						? "保存中"
						: "Saving"
					: isChineseUi
						? "保存"
						: "Save"}
			</button>
			<button
				className="fa-observability-preset"
				disabled={disabled}
				type="button"
				onClick={onReset}
			>
				{isChineseUi ? "重置" : "Reset"}
			</button>
		</div>
	);
}

function ReadOnlyConfigValue({
	isChineseUi,
	item,
}: {
	isChineseUi: boolean;
	item: FocusAgentAdminConfigValue;
}) {
	const copy = localizedConfigValueCopy(item, isChineseUi);
	const value = item.sensitive
		? item.configured
			? isChineseUi
				? "已配置"
				: "Configured"
			: isChineseUi
				? "未配置"
				: "Not configured"
		: unknownToText(item.value) || "-";
	return (
		<div className="fa-admin-config-value-row">
			<div className="fa-admin-config-readonly-head">
				<strong>{copy.label}</strong>
				<span>{item.env_key || item.key}</span>
			</div>
			<output>{value}</output>
			{copy.description ? <p>{copy.description}</p> : null}
		</div>
	);
}
