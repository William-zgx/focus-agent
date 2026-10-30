import { normalizeText, parseJsonValue } from "./message-transcript-normalize";

// Tool-call field access and skill-id extraction for transcript building.
// Tool calls arrive in LangChain ({ name, args }) or OpenAI
// ({ function: { name, arguments } }) shape.

export function recordValue(value: unknown): Record<string, unknown> | null {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		return null;
	}
	return value as Record<string, unknown>;
}

function arrayValue(value: unknown): unknown[] {
	return Array.isArray(value) ? value : [];
}

export function stringListValue(value: unknown): string[] {
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

export function collectSkillIdsFromMetadata(value: unknown): string[] {
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

export function collectSkillIdsFromRecordMetadata(
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

export function toolCallId(call: Record<string, unknown>, fallback: string) {
	return normalizeText(call.id) || normalizeText(call.tool_call_id) || fallback;
}

export function toolCallName(call: Record<string, unknown>) {
	return (
		normalizeText(call.name) ||
		normalizeText((call.function as Record<string, unknown> | undefined)?.name)
	);
}

function toolCallRawArgsValue(call: Record<string, unknown>) {
	return (
		call.args ??
		(call.function as Record<string, unknown> | undefined)?.arguments ??
		call.arguments
	);
}

export function toolCallArgsText(call: Record<string, unknown>) {
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

export function collectSkillIdsFromToolCall(
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

export function collectSkillIdsFromToolMessage(
	message: Record<string, unknown>,
	toolName: string,
	content: string,
) {
	return [
		...collectSkillIdsFromRecordMetadata(message),
		...collectSkillIdsFromSkillPayload(content, toolName),
	];
}
