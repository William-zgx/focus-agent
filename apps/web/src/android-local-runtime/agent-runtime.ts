import {
	ANDROID_LOCAL_TOOL_NAME_SET,
	ANDROID_LOCAL_TOOL_NAMES,
	DEFAULT_MODEL_ID,
	LOCAL_USER_ID,
} from "./constants";
import {
	errorResponse,
	isRecord,
	jsonResponse,
	nowIso,
	nullableString,
	parseJsonBody,
	searchParamNumber,
	stringArray,
	stringValue,
} from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { ANDROID_LOCAL_SKILLS } from "./skills";
import { defaultAdminConfig } from "./state";

export function localAgentEmptyList(_ctx: LocalFocusAgentRuntime, limit = 50) {
	return {
		items: [],
		count: 0,
		trajectory_available: true,
		trajectory_error: null,
		limit,
	};
}

export function localTool(ctx: LocalFocusAgentRuntime, name: string) {
	if (!ANDROID_LOCAL_TOOL_NAME_SET.has(name)) return null;
	return (
		ctx.state.adminConfig.tools.tools.find((tool) => tool.name === name) ??
		defaultAdminConfig().tools.tools.find((tool) => tool.name === name) ??
		null
	);
}

export function localEnabledTools(ctx: LocalFocusAgentRuntime) {
	return ANDROID_LOCAL_TOOL_NAMES.flatMap((name) => {
		const tool = ctx.localTool(name);
		return tool?.enabled === false ? [] : tool ? [tool] : [];
	});
}

export function localToolEnabled(
	ctx: LocalFocusAgentRuntime,
	name: string,
): boolean {
	return Boolean(ctx.localTool(name)?.enabled);
}

export function localCapabilities(ctx: LocalFocusAgentRuntime) {
	return ctx.localEnabledTools().map((tool) => ({
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

export function localRolePolicy(ctx: LocalFocusAgentRuntime) {
	const model =
		ctx.state.adminConfig.models.default_model ||
		ctx.state.adminConfig.models.model_choices[0] ||
		DEFAULT_MODEL_ID;
	return {
		enabled: true,
		default_model: model,
		helper_model: ctx.state.adminConfig.models.helper_model ?? model,
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

export function localRoleDecision(
	ctx: LocalFocusAgentRuntime,
	message: string,
	role = "planner",
) {
	const model =
		ctx.state.adminConfig.models.default_model ||
		ctx.state.adminConfig.models.model_choices[0] ||
		DEFAULT_MODEL_ID;
	return {
		role,
		model_id: model,
		rationale:
			"Android local runtime uses the selected local model for governance previews.",
		route_reason: "android-local-runtime",
		confidence: message.trim() ? 0.72 : 0.5,
		tool_governance: {
			available_tools: ctx.localCapabilities().map((item) => item.name),
			runtime: "android-local",
		},
	};
}

export function localSkillCatalogItems(_ctx: LocalFocusAgentRuntime) {
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

export function localSelectedSkills(
	ctx: LocalFocusAgentRuntime,
	message: string,
	hints: string[] = [],
) {
	const normalized = message.toLowerCase();
	const hinted = new Set(hints);
	const selected = ctx.localSkillCatalogItems().filter((skill) => {
		if (hinted.has(String(skill.skill_id)) || hinted.has(String(skill.name))) {
			return true;
		}
		return stringArray(skill.triggers).some((trigger) =>
			normalized.includes(trigger.toLowerCase()),
		);
	});
	return selected.length ? selected : ctx.localSkillCatalogItems().slice(0, 1);
}

export function localContextEvidenceRecord(
	ctx: LocalFocusAgentRuntime,
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
		evidence_id: ctx.nextId("audit", "local-context-evidence"),
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

export function handleLocalAgentMemory(
	ctx: LocalFocusAgentRuntime,
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
	if (subresource === "curator" && third === "evaluate" && method === "POST") {
		return jsonResponse({
			decision: {
				status: "skipped",
				reason: "Android local runtime keeps memory curation local.",
			},
		});
	}
	if (subresource === "curator" && third === "decisions" && method === "GET") {
		return jsonResponse(ctx.localAgentEmptyList(limit));
	}
	if (subresource && third === "usage" && method === "GET") {
		return jsonResponse({ memory_id: subresource, usage: [], count: 0 });
	}
	return errorResponse(404, "Unsupported local agent memory route.");
}

export function handleLocalAgentDelegation(
	ctx: LocalFocusAgentRuntime,
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
	if (subresource === "policy" && method === "GET") return jsonResponse(policy);
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
		return jsonResponse(ctx.localAgentEmptyList(limit));
	}
	return errorResponse(404, "Unsupported local agent delegation route.");
}

export function handleLocalAgentModelRouter(
	ctx: LocalFocusAgentRuntime,
	method: string,
	subresource?: string,
	limit = 50,
	init?: RequestInit,
): Response {
	const policy = {
		enabled: true,
		mode: "local",
		default_model:
			ctx.state.adminConfig.models.default_model || DEFAULT_MODEL_ID,
		helper_model: ctx.state.adminConfig.models.helper_model ?? null,
		role_models: ctx.localRolePolicy().role_models,
	};
	if (subresource === "policy" && method === "GET") return jsonResponse(policy);
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
		return jsonResponse(ctx.localAgentEmptyList(limit));
	}
	return errorResponse(404, "Unsupported local agent model router route.");
}

export function handleLocalAgentContext(
	ctx: LocalFocusAgentRuntime,
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
		return jsonResponse(ctx.localAgentEmptyList(limit));
	}
	if (subresource === "artifacts" && method === "GET") {
		return jsonResponse(ctx.localAgentEmptyList(limit));
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
		const evidence = ctx.localContextEvidenceRecord(body);
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

export function handleLocalAgentTaskLedger(
	ctx: LocalFocusAgentRuntime,
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
	if (subresource === "policy" && method === "GET") return jsonResponse(policy);
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
		return jsonResponse(ctx.localAgentEmptyList(limit));
	}
	return errorResponse(404, "Unsupported local agent task ledger route.");
}

export function handleAgent(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	searchParams: URLSearchParams,
	init?: RequestInit,
): Response {
	const [resource, subresource, third, fourth] = segments;
	const limit = searchParamNumber(searchParams, "limit", 50);
	if (resource === "capabilities" && method === "GET") {
		const items = ctx.localCapabilities();
		return jsonResponse({ items, count: items.length });
	}
	if (resource === "toolsets" && method === "GET") {
		const capabilities = ctx.localCapabilities();
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
		const enabledToolNames = ctx.localCapabilities().map((item) => item.name);
		const availableTools = stringArray(body.available_tools);
		const allowed = availableTools.length
			? availableTools.filter((toolName) => enabledToolNames.includes(toolName))
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
		return jsonResponse(ctx.localAgentEmptyList(limit));
	}
	if (resource === "roles" && subresource === "policy" && method === "GET") {
		return jsonResponse(ctx.localRolePolicy());
	}
	if (resource === "roles" && subresource === "dry-run" && method === "POST") {
		const body = parseJsonBody(init) as { message?: string };
		return jsonResponse({
			policy: ctx.localRolePolicy(),
			plan: {
				role: "planner",
				decisions: [ctx.localRoleDecision(body.message ?? "", "planner")],
				reason: "Android local runtime uses a lightweight role router.",
				message: body.message ?? "",
			},
		});
	}
	if (resource === "roles" && subresource === "decisions" && method === "GET") {
		return jsonResponse(ctx.localAgentEmptyList(limit));
	}
	if (resource === "skills" && subresource === "catalog" && method === "GET") {
		const items = ctx.localSkillCatalogItems();
		return jsonResponse({ items, count: items.length });
	}
	if (resource === "skills" && subresource === "select" && method === "POST") {
		const body = parseJsonBody(init) as {
			message?: string;
			skill_hints?: string[];
		};
		const selected = ctx.localSelectedSkills(
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
		return jsonResponse(ctx.localAgentEmptyList(limit));
	}
	if (
		resource === "skills" &&
		subresource &&
		third === "preference" &&
		method === "PATCH"
	) {
		const body = parseJsonBody(init) as {
			metadata?: Record<string, unknown>;
			state?: string;
		};
		const skill =
			ctx
				.localSkillCatalogItems()
				.find(
					(item) => item.skill_id === subresource || item.name === subresource,
				) ?? ctx.localSkillCatalogItems()[0];
		return jsonResponse({
			preference_id: `android-local:${skill.skill_id}`,
			user_id: LOCAL_USER_ID,
			skill_id: skill.skill_id,
			state: body.state ?? "default",
			metadata: body.metadata ?? {},
			created_at: nowIso(),
			updated_at: nowIso(),
		});
	}
	if (
		resource === "skills" &&
		subresource === "selections" &&
		fourth === "feedback"
	) {
		return jsonResponse({ items: [], count: 0 });
	}
	if (resource === "feedback" && subresource === "trend" && method === "GET") {
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
		return ctx.handleLocalAgentMemory(method, subresource, third, limit);
	}
	if (resource === "delegation") {
		return ctx.handleLocalAgentDelegation(method, subresource, limit, init);
	}
	if (resource === "model-router") {
		return ctx.handleLocalAgentModelRouter(method, subresource, limit, init);
	}
	if (resource === "self-repair") {
		return subresource === "failures" && method === "GET"
			? jsonResponse(ctx.localAgentEmptyList(limit))
			: jsonResponse({ preview: { items: [], runtime: "android-local" } });
	}
	if (resource === "review-queue") {
		if (!subresource && method === "GET")
			return jsonResponse(ctx.localAgentEmptyList(limit));
		return jsonResponse({
			item: { id: subresource, status: third ?? "decided" },
		});
	}
	if (resource === "context") {
		return ctx.handleLocalAgentContext(method, subresource, limit, init);
	}
	if (resource === "task-ledger") {
		return ctx.handleLocalAgentTaskLedger(method, subresource, limit, init);
	}
	if (resource === "artifacts") {
		if (!subresource && method === "GET")
			return jsonResponse(ctx.localAgentEmptyList(limit));
		return jsonResponse({
			result: { artifacts: [], runtime: "android-local" },
		});
	}
	if (resource === "critic") {
		if (subresource === "verdicts" && method === "GET") {
			return jsonResponse(ctx.localAgentEmptyList(limit));
		}
		return jsonResponse({
			result: { verdict: "pass", runtime: "android-local" },
		});
	}
	return errorResponse(404, "Unsupported local agent governance route.");
}
