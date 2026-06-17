import type { ThreadStateResponse } from "@focus-agent/web-sdk";
import { DEFAULT_MODEL_ID, LOCAL_TENANT_ID, LOCAL_USER_ID } from "./constants";
import {
	errorResponse,
	jsonResponse,
	nowIso,
	nullableString,
	parseJsonBody,
	searchParamNumber,
	stringValue,
} from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import type { JsonRecord } from "./types";

export function localMemoryRecords(ctx: LocalFocusAgentRuntime) {
	const forgottenMemoryIds = new Set(ctx.state.forgottenMemoryIds ?? []);
	return Object.values(ctx.state.threads)
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

export function localTrajectoryList(
	ctx: LocalFocusAgentRuntime,
	searchParams: URLSearchParams,
) {
	const limit = searchParamNumber(searchParams, "limit", 50);
	const offset = searchParamNumber(searchParams, "offset", 0);
	const items = Object.values(ctx.state.threads)
		.map((thread) => ctx.localTrajectorySummary(thread))
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

export function localTrajectorySummary(
	_ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
) {
	const threadRecord = thread as unknown as JsonRecord;
	const messages = (thread.messages ?? []) as Array<Record<string, unknown>>;
	const humanMessages = messages.filter((message) => message.type === "human");
	const aiMessages = messages.filter((message) => message.type === "ai");
	const toolMessages = messages.filter((message) => message.type === "tool");
	const lastHumanMessage = humanMessages[humanMessages.length - 1];
	const lastAiMessage = aiMessages[aiMessages.length - 1];
	const userMessage = stringValue(lastHumanMessage?.content);
	const answer = stringValue(
		lastAiMessage?.content || thread.assistant_message,
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

export function localTrajectoryDetail(
	ctx: LocalFocusAgentRuntime,
	turnId: string,
) {
	const thread = Object.values(ctx.state.threads).find(
		(item) => `local-turn-${item.thread_id}` === turnId,
	);
	if (!thread) return null;
	const summary = ctx.localTrajectorySummary(thread);
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
			error: message.status === "failed" ? stringValue(message.content) : null,
			cache_hit: false,
			fallback_used: false,
			fallback_group: null,
			parallel_batch_size: null,
			runtime: { runtime: "android-local" },
			observation_truncated: false,
		})),
	};
}

export function localTrajectoryStats(ctx: LocalFocusAgentRuntime) {
	const items = Object.values(ctx.state.threads).map((thread) =>
		ctx.localTrajectorySummary(thread),
	);
	const totalToolCalls = items.reduce((sum, item) => sum + item.tool_calls, 0);
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
		by_tool: ctx.state.adminConfig.tools.tools.map((tool) => ({
			key: tool.name,
			turn_count: items.length,
			step_count: 0,
			total_tool_calls: 0,
		})),
	};
}

export function localObservabilityOverview(
	ctx: LocalFocusAgentRuntime,
	searchParams: URLSearchParams,
) {
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
		stats: ctx.localTrajectoryStats(),
	};
}

export function localTrajectoryReplay(
	ctx: LocalFocusAgentRuntime,
	detail: JsonRecord,
	model?: string | null,
) {
	const modelUsed =
		nullableString(model) ||
		ctx.state.adminConfig.models.default_model ||
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

export function localTrajectoryPromotion(
	_ctx: LocalFocusAgentRuntime,
	detail: JsonRecord,
) {
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

export function handleMemory(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	searchParams: URLSearchParams,
	init?: RequestInit,
): Response {
	const [memoryId, action] = segments;
	if (!memoryId && method === "GET") {
		const limit = searchParamNumber(searchParams, "limit", 50);
		const offset = searchParamNumber(searchParams, "offset", 0);
		const items = ctx
			.localMemoryRecords()
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
		const items = ctx.state.auditEvents
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
	const item = ctx
		.localMemoryRecords()
		.find((record) => record.memory_id === memoryId);
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
		const auditId = ctx.nextId("audit", "local-audit");
		const forgottenMemoryIds = new Set(ctx.state.forgottenMemoryIds ?? []);
		forgottenMemoryIds.add(item.memory_id);
		ctx.state.forgottenMemoryIds = [...forgottenMemoryIds];
		ctx.state.auditEvents.unshift({
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
		ctx.persist();
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

export function handleObservability(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	searchParams: URLSearchParams,
	init?: RequestInit,
): Response {
	const [resource, subresource, action, nestedAction] = segments;
	if (resource === "overview" && method === "GET") {
		return jsonResponse(ctx.localObservabilityOverview(searchParams));
	}
	if (resource !== "trajectory") {
		return errorResponse(404, "Unsupported local observability route.");
	}
	if (!subresource && method === "GET") {
		return jsonResponse(ctx.localTrajectoryList(searchParams));
	}
	if (subresource === "stats" && method === "GET") {
		return jsonResponse({
			filters: Object.fromEntries(searchParams.entries()),
			stats: ctx.localTrajectoryStats(),
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
	const detail = ctx.localTrajectoryDetail(subresource);
	if (!detail) return errorResponse(404, "Trajectory turn not found.");
	if (!action && method === "GET") {
		return jsonResponse({ item: detail });
	}
	if (action === "replay" && method === "POST") {
		const body = parseJsonBody(init) as { model?: string | null };
		return jsonResponse(ctx.localTrajectoryReplay(detail, body.model));
	}
	if (action === "promote" && method === "POST") {
		return jsonResponse(ctx.localTrajectoryPromotion(detail));
	}
	if (nestedAction) {
		return errorResponse(404, "Unsupported local trajectory route.");
	}
	return errorResponse(404, "Unsupported local trajectory route.");
}
