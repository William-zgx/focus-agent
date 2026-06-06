import { safeVisibleText } from "@focus-agent/web-sdk";

import {
	normalizeMessageType,
	normalizeText,
	parseJsonValue,
} from "./message-transcript-normalize";
import type {
	ProcessingStepEntry,
	ToolActivityItem,
	ToolDetailEntry,
	TranscriptItem,
} from "./message-transcript-types";
import {
	formatToolDetailContent,
	summarizeToolResult,
	totalTokensFromUsageMetadata,
	truncateText,
	uniqueToolNames,
} from "./message-transcript-tool-summary";
import {
	shouldHideStreamingInternalContent,
	visibleAssistantIndexesToHide,
} from "./message-transcript-visibility";

function appendUniqueValues(target: string[], values: string[]) {
	for (const value of values) {
		const normalized = normalizeText(value);
		if (normalized && !target.includes(normalized)) {
			target.push(normalized);
		}
	}
}

function recordValue(value: unknown): Record<string, unknown> | null {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		return null;
	}
	return value as Record<string, unknown>;
}

function arrayValue(value: unknown): unknown[] {
	return Array.isArray(value) ? value : [];
}

function stringListValue(value: unknown): string[] {
	if (typeof value === "string") {
		const normalized = normalizeText(value);
		return normalized ? [normalized] : [];
	}
	if (!Array.isArray(value)) {
		return [];
	}
	return value
		.map((item) => normalizeText(item))
		.filter((item) => Boolean(item));
}

function parsedJsonLikeValue(value: unknown): unknown | null {
	if (typeof value === "string") {
		return parseJsonValue(value);
	}
	if (value && typeof value === "object") {
		return value;
	}
	return null;
}

function collectSkillIdsFromMetadata(value: unknown): string[] {
	const record = recordValue(value);
	if (!record) {
		return [];
	}

	const skillIds = [
		...stringListValue(record.skill_id),
		...stringListValue(record.skill_ids),
		...stringListValue(record.active_skill_ids),
		...stringListValue(record.selected_skill_ids),
	];
	for (const skill of arrayValue(record.active_skills)) {
		const skillRecord = recordValue(skill);
		if (skillRecord) {
			skillIds.push(...stringListValue(skillRecord.skill_id));
		}
	}
	const skillRecord = recordValue(record.skill);
	if (skillRecord) {
		skillIds.push(...stringListValue(skillRecord.skill_id));
	}
	const skillExecutionPlan = recordValue(record.skill_execution_plan);
	if (skillExecutionPlan) {
		skillIds.push(...stringListValue(skillExecutionPlan.selected_skill_ids));
	}
	const focusAgentRecord = recordValue(record.focus_agent);
	if (focusAgentRecord) {
		skillIds.push(...collectSkillIdsFromMetadata(focusAgentRecord));
	}
	const turnMetadataRecord = recordValue(record.turn_metadata);
	if (turnMetadataRecord) {
		skillIds.push(...collectSkillIdsFromMetadata(turnMetadataRecord));
	}
	return skillIds;
}

function collectSkillIdsFromRecordMetadata(
	record: Record<string, unknown>,
): string[] {
	return [
		...collectSkillIdsFromMetadata(record),
		...collectSkillIdsFromMetadata(record.metadata),
		...collectSkillIdsFromMetadata(record.turn_metadata),
		...collectSkillIdsFromMetadata(record.response_metadata),
		...collectSkillIdsFromMetadata(record.additional_kwargs),
		...collectSkillIdsFromMetadata(
			recordValue(record.additional_kwargs)?.metadata,
		),
		...collectSkillIdsFromMetadata(
			recordValue(record.additional_kwargs)?.focus_agent,
		),
		...collectSkillIdsFromMetadata(
			recordValue(record.additional_kwargs)?.turn_metadata,
		),
	];
}

function turnMetadataFromMessage(
	message: Record<string, unknown>,
): Record<string, unknown> | null {
	const direct = recordValue(message.turn_metadata);
	if (direct) {
		return direct;
	}
	const focusAgent = recordValue(
		recordValue(message.response_metadata)?.focus_agent,
	);
	if (focusAgent) {
		return focusAgent;
	}
	const additionalFocusAgent = recordValue(
		recordValue(message.additional_kwargs)?.focus_agent,
	);
	return additionalFocusAgent;
}

function hasSkillExecutionMetadata(metadata: Record<string, unknown> | null) {
	return Boolean(
		recordValue(metadata?.skill_execution_plan) ||
			recordValue(metadata?.execution_contract) ||
			recordValue(metadata?.answer_verification),
	);
}

function skillExecutionPlanContent(plan: Record<string, unknown>) {
	const selectedSkillIds = stringListValue(plan.selected_skill_ids);
	const primaryTools = stringListValue(plan.primary_tools);
	const supportingTools = stringListValue(plan.supporting_tools);
	const runtimeCwds = recordValue(plan.runtime_cwds);
	const cwdText = runtimeCwds
		? Object.entries(runtimeCwds)
				.map(([skillId, cwd]) => `${skillId}: ${normalizeText(cwd)}`)
				.filter(Boolean)
				.join("; ")
		: "";
	const parts = [
		selectedSkillIds.length > 0
			? `selected: ${selectedSkillIds.join(", ")}`
			: "",
		primaryTools.length > 0 ? `primary: ${primaryTools.join(", ")}` : "",
		supportingTools.length > 0
			? `supporting: ${supportingTools.join(", ")}`
			: "",
		cwdText ? `cwd: ${cwdText}` : "",
	].filter(Boolean);
	return parts.join("; ");
}

function executionContractContent(contract: Record<string, unknown>) {
	const requiredTools = stringListValue(contract.required_tools);
	const missingTools = stringListValue(contract.missing);
	const selectedSkillIds = stringListValue(contract.selected_skill_ids);
	const status = normalizeText(contract.status);
	const parts = [
		status ? `status: ${status}` : "",
		selectedSkillIds.length > 0 ? `skill: ${selectedSkillIds.join(", ")}` : "",
		requiredTools.length > 0 ? `required: ${requiredTools.join(", ")}` : "",
		missingTools.length > 0 ? `missing: ${missingTools.join(", ")}` : "",
	].filter(Boolean);
	return parts.join("; ");
}

function contractTone(status: string): ProcessingStepEntry["tone"] {
	if (status === "satisfied") {
		return "success";
	}
	if (status === "blocked") {
		return "danger";
	}
	if (status === "missing_required_tools") {
		return "warn";
	}
	return "neutral";
}

function contractStepStatus(status: string): ProcessingStepEntry["status"] {
	if (status === "satisfied") {
		return "completed";
	}
	if (status === "blocked") {
		return "failed";
	}
	if (status === "missing_required_tools") {
		return "running";
	}
	return "pending";
}

function skillIdFromSkillPath(value: unknown): string {
	if (typeof value !== "string") {
		return "";
	}
	const normalized = value.replace(/\\/g, "/");
	const match = normalized.match(/(?:^|\/)\.focus_agent\/skills\/([^/]+)/);
	return normalizeText(match?.[1]);
}

function collectSkillIdsFromCwd(value: unknown): string[] {
	const record = recordValue(value);
	if (!record) {
		return [];
	}

	const skillIds: string[] = [];
	const cwdSkillId = skillIdFromSkillPath(record.cwd);
	if (cwdSkillId) {
		skillIds.push(cwdSkillId);
	}
	return skillIds;
}

function collectSkillIdsFromSkillPayload(
	value: unknown,
	toolName: string,
): string[] {
	const parsed = parsedJsonLikeValue(value);
	const record = recordValue(parsed);
	if (!record) {
		return [];
	}

	const skillIds = collectSkillIdsFromRecordMetadata(record);
	const normalizedToolName = normalizeText(toolName).toLowerCase();
	const isSkillTool =
		normalizedToolName === "skills_search" ||
		normalizedToolName === "skill_view" ||
		normalizedToolName === "skill_install" ||
		normalizedToolName === "skill_select";

	if (normalizedToolName === "skills_search") {
		const firstResult = recordValue(arrayValue(record.results)[0]);
		if (firstResult) {
			skillIds.push(...stringListValue(firstResult.skill_id));
		}
	}

	if (isSkillTool || Array.isArray(record.recommended_tools)) {
		skillIds.push(...stringListValue(record.skill_id));
		skillIds.push(...stringListValue(record.skill_ids));
	}

	const skillRecord = recordValue(record.skill);
	if (skillRecord && Array.isArray(skillRecord.recommended_tools)) {
		skillIds.push(...stringListValue(skillRecord.skill_id));
	}

	return skillIds;
}

export function buildTranscriptItems(
	messages: Array<Record<string, unknown>>,
	assistantMessage?: string | null,
): TranscriptItem[] {
	const items: TranscriptItem[] = [];
	let pendingToolActivity: ToolActivityItem | null = null;
	let latestHumanIndex = -1;
	let hasVisibleAssistantAfterLatestHuman = false;
	const hiddenVisibleAssistantIndexes = visibleAssistantIndexesToHide(messages);

	for (let index = 0; index < messages.length; index += 1) {
		if (normalizeMessageType(messages[index]?.type) === "human") {
			latestHumanIndex = index;
		}
	}

	function flushToolActivity() {
		if (!pendingToolActivity) {
			return;
		}
		pendingToolActivity.toolNames = uniqueToolNames(
			pendingToolActivity.toolNames,
		);
		pendingToolActivity.skillIds = uniqueToolNames(
			pendingToolActivity.skillIds,
		);
		pendingToolActivity.summaryText = truncateText(
			pendingToolActivity.summaryText,
		);
		items.push(pendingToolActivity);
		pendingToolActivity = null;
	}

	function createToolActivity(id: string): ToolActivityItem {
		return {
			kind: "tool-activity",
			id,
			skillIds: [],
			toolNames: [],
			summaryText: "",
			details: [],
			steps: [],
		};
	}

	function toolCallId(call: Record<string, unknown>, fallback: string) {
		return (
			normalizeText(call.id) || normalizeText(call.tool_call_id) || fallback
		);
	}

	function toolCallName(call: Record<string, unknown>) {
		return (
			normalizeText(call.name) ||
			normalizeText(
				(call.function as Record<string, unknown> | undefined)?.name,
			)
		);
	}

	function toolCallRawArgsValue(call: Record<string, unknown>) {
		return (
			call.args ??
			(call.function as Record<string, unknown> | undefined)?.arguments ??
			call.arguments
		);
	}

	function toolCallArgsText(call: Record<string, unknown>) {
		const args = toolCallRawArgsValue(call);
		if (typeof args === "string") {
			return normalizeText(args);
		}
		if (args && typeof args === "object") {
			return JSON.stringify(args, null, 2);
		}
		return "";
	}

	function toolCallArgsValue(call: Record<string, unknown>) {
		const args = toolCallRawArgsValue(call);
		if (typeof args === "string") {
			return parseJsonValue(args) ?? normalizeText(args);
		}
		return args;
	}

	function collectSkillIdsFromToolCall(
		call: Record<string, unknown>,
		toolName: string,
	) {
		const args = toolCallArgsValue(call);
		return [
			...collectSkillIdsFromRecordMetadata(call),
			...collectSkillIdsFromSkillPayload(args, toolName),
			...collectSkillIdsFromCwd(args),
		];
	}

	function collectSkillIdsFromToolMessage(
		message: Record<string, unknown>,
		toolName: string,
		content: string,
	) {
		return [
			...collectSkillIdsFromRecordMetadata(message),
			...collectSkillIdsFromSkillPayload(content, toolName),
		];
	}

	function upsertToolStep(
		activity: ToolActivityItem,
		step: ProcessingStepEntry,
	) {
		const existingIndex = activity.steps.findIndex(
			(item) => item.id === step.id,
		);
		if (existingIndex >= 0) {
			activity.steps[existingIndex] = {
				...activity.steps[existingIndex],
				...step,
			};
			return;
		}
		activity.steps.push(step);
	}

	function completeMatchingToolStep(
		activity: ToolActivityItem,
		toolCallId: string,
		toolName: string,
		detail: ToolDetailEntry | null,
		content: string,
		hasFailed: boolean,
	) {
		const existingIndex = activity.steps.findIndex(
			(step) =>
				step.id === toolCallId ||
				(step.kind === "tool" &&
					step.label === toolName &&
					step.status !== "completed"),
		);
		const label = toolName || `tool-${activity.steps.length + 1}`;
		const step: ProcessingStepEntry = {
			id: toolCallId || `${activity.id}-step-${activity.steps.length}`,
			kind: "tool",
			label,
			status: hasFailed ? "failed" : "completed",
			tone: hasFailed ? "danger" : "success",
			content: summarizeToolResult(content),
			detail: detail ?? undefined,
		};
		if (existingIndex >= 0) {
			const existingStep = activity.steps[existingIndex];
			activity.steps[existingIndex] = {
				...existingStep,
				...step,
				id: existingStep.id,
				label: toolName || existingStep.label || step.label,
			};
			return;
		}
		activity.steps.push(step);
	}

	function appendSkillExecutionMetadataSteps(
		activity: ToolActivityItem,
		metadata: Record<string, unknown>,
		messageId: string,
	) {
		appendUniqueValues(
			activity.skillIds,
			collectSkillIdsFromMetadata(metadata),
		);

		const plan = recordValue(metadata.skill_execution_plan);
		if (plan) {
			const primaryTools = stringListValue(plan.primary_tools);
			appendUniqueValues(activity.toolNames, primaryTools);
			upsertToolStep(activity, {
				id: `${activity.id}-${messageId}-skill-plan`,
				kind: "skill",
				label: "Skill plan",
				status: "completed",
				tone: "neutral",
				content: skillExecutionPlanContent(plan),
			});
		}

		const contract = recordValue(metadata.execution_contract);
		if (contract) {
			const status = normalizeText(contract.status);
			const requiredTools = stringListValue(contract.required_tools);
			appendUniqueValues(activity.toolNames, requiredTools);
			upsertToolStep(activity, {
				id: `${activity.id}-${messageId}-skill-contract`,
				kind: "skill",
				label: "Required tools",
				status: contractStepStatus(status),
				tone: contractTone(status),
				content: executionContractContent(contract),
			});
		}

		const verification = recordValue(metadata.answer_verification);
		const repairAction =
			normalizeText(verification?.repair_action_taken) ||
			normalizeText(verification?.repair_action);
		if (verification && repairAction) {
			upsertToolStep(activity, {
				id: `${activity.id}-${messageId}-skill-repair`,
				kind: "skill",
				label: "Repair",
				status:
					repairAction === "retry_skill_primary_tool" ? "running" : "completed",
				tone: repairAction === "answer_with_uncertainty" ? "danger" : "warn",
				content: `action: ${repairAction}`,
			});
		}
	}

	for (let index = 0; index < messages.length; index += 1) {
		const message = messages[index] ?? {};
		const type = normalizeMessageType(message.type);
		const rawContent = String(message.content ?? "");
		const content = type === "tool" ? rawContent : safeVisibleText(rawContent);
		const messageId = String(message.id ?? `${type || "message"}-${index}`);
		const toolCalls = Array.isArray(message.tool_calls)
			? (message.tool_calls as Array<Record<string, unknown>>)
			: [];
		const turnMetadata = turnMetadataFromMessage(message);
		if (hasSkillExecutionMetadata(turnMetadata)) {
			if (!pendingToolActivity) {
				pendingToolActivity = createToolActivity(`tool-activity-${messageId}`);
			}
			appendSkillExecutionMetadataSteps(
				pendingToolActivity,
				turnMetadata as Record<string, unknown>,
				messageId,
			);
		}

		if (type === "ai" && toolCalls.length > 0) {
			if (!pendingToolActivity) {
				pendingToolActivity = createToolActivity(`tool-activity-${messageId}`);
			}
			appendUniqueValues(
				pendingToolActivity.skillIds,
				collectSkillIdsFromRecordMetadata(message),
			);
			for (const [callIndex, call] of toolCalls.entries()) {
				const toolName = toolCallName(call);
				if (toolName) {
					pendingToolActivity.toolNames.push(toolName);
				}
				appendUniqueValues(
					pendingToolActivity.skillIds,
					collectSkillIdsFromToolCall(call, toolName),
				);
				const argsText = toolCallArgsText(call);
				upsertToolStep(pendingToolActivity, {
					id: toolCallId(
						call,
						`${pendingToolActivity.id}-${messageId}-call-${callIndex}`,
					),
					kind: "tool",
					label: toolName || `tool-${callIndex + 1}`,
					status: "running",
					tone: "warn",
					content: argsText,
				});
			}
			continue;
		}

		if (type === "tool") {
			if (!pendingToolActivity) {
				pendingToolActivity = createToolActivity(`tool-activity-${messageId}`);
			}

			const toolName = normalizeText(message.name);
			const toolCallId = normalizeText(message.tool_call_id) || messageId;
			const hasFailed = ["error", "failed"].includes(
				normalizeText(message.status).toLowerCase(),
			);
			if (toolName) {
				pendingToolActivity.toolNames.push(toolName);
			}
			if (!pendingToolActivity.summaryText) {
				pendingToolActivity.summaryText = summarizeToolResult(content);
			}
			const matchedStep = pendingToolActivity.steps.find(
				(step) =>
					step.id === toolCallId ||
					(Boolean(toolName) &&
						step.kind === "tool" &&
						step.label === toolName &&
						step.status !== "completed"),
			);
			const inferredToolName = toolName || matchedStep?.label || "";
			appendUniqueValues(
				pendingToolActivity.skillIds,
				collectSkillIdsFromToolMessage(message, inferredToolName, content),
			);
			const detail = formatToolDetailContent(content);
			let detailEntry: ToolDetailEntry | null = null;
			if (detail.content) {
				detailEntry = {
					id: `${pendingToolActivity.id}-detail-${pendingToolActivity.details.length}`,
					label:
						toolName ||
						matchedStep?.label ||
						`tool-${pendingToolActivity.details.length + 1}`,
					content: detail.content,
					language: detail.language,
				};
				pendingToolActivity.details.push(detailEntry);
			}
			completeMatchingToolStep(
				pendingToolActivity,
				toolCallId,
				toolName,
				detailEntry,
				content,
				hasFailed,
			);
			continue;
		}

		if (
			!normalizeText(content) ||
			shouldHideStreamingInternalContent(content) ||
			(type === "ai" && hiddenVisibleAssistantIndexes.has(index))
		) {
			if (type === "human" || type === "system") {
				flushToolActivity();
			}
			continue;
		}

		flushToolActivity();

		const item = {
			kind: "message",
			id: messageId,
			type: type || "message",
			content,
			totalTokens:
				type === "ai"
					? totalTokensFromUsageMetadata(message.usage_metadata)
					: 0,
		} as const;
		items.push(item);
		if (type === "ai" && index > latestHumanIndex) {
			hasVisibleAssistantAfterLatestHuman = true;
		}
	}

	flushToolActivity();

	const normalizedAssistantMessage = normalizeText(
		safeVisibleText(assistantMessage ?? ""),
	);
	const shouldHideAssistantFallback = shouldHideStreamingInternalContent(
		normalizedAssistantMessage,
	);
	const hasVisibleAssistantMessage = items.some(
		(item) =>
			item.kind === "message" &&
			normalizeMessageType(item.type) === "ai" &&
			normalizeText(item.content) === normalizedAssistantMessage,
	);

	if (
		normalizedAssistantMessage &&
		!hasVisibleAssistantMessage &&
		!hasVisibleAssistantAfterLatestHuman &&
		!shouldHideAssistantFallback
	) {
		items.push({
			kind: "message",
			id: "assistant-message-fallback",
			type: "ai",
			content: normalizedAssistantMessage,
			totalTokens: 0,
		});
		return items;
	}

	return items;
}
