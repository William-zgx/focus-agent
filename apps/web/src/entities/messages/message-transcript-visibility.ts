import { looksLikeTextualToolCallArtifact } from "@focus-agent/web-sdk";

import {
	normalizeMessageType,
	normalizeText,
	parseJsonValue,
} from "./message-transcript-normalize";

function looksLikeInternalToolMarkup(value: unknown) {
	return looksLikeTextualToolCallArtifact(normalizeText(value));
}

function looksLikeToolPlanningPayload(value: unknown) {
	const text = normalizeText(value);
	if (!text) {
		return false;
	}

	const lowered = text.toLowerCase();
	if (
		(lowered.includes('"steps"') || lowered.includes('"step"')) &&
		lowered.includes('"expected_tools"')
	) {
		return true;
	}

	const parsed = parseJsonValue(text);
	if (!parsed || typeof parsed !== "object") {
		return false;
	}

	if (!("steps" in parsed) || !Array.isArray(parsed.steps)) {
		return false;
	}

	return parsed.steps.some((step) => {
		if (!step || typeof step !== "object") {
			return false;
		}
		const record = step as Record<string, unknown>;
		return (
			Array.isArray(record.expected_tools) || typeof record.goal === "string"
		);
	});
}

export function shouldHideStreamingInternalContent(value: unknown) {
	return (
		looksLikeInternalToolMarkup(value) || looksLikeToolPlanningPayload(value)
	);
}

export function visibleAssistantIndexesToHide(
	messages: Array<Record<string, unknown>>,
) {
	const hidden = new Set<number>();
	let visibleIndexesInTurn: number[] = [];

	function closeTurn() {
		for (const index of visibleIndexesInTurn.slice(0, -1)) {
			hidden.add(index);
		}
		visibleIndexesInTurn = [];
	}

	for (let index = 0; index < messages.length; index += 1) {
		const message = messages[index] ?? {};
		const type = normalizeMessageType(message.type);

		if (type === "human") {
			closeTurn();
			continue;
		}

		const toolCalls = Array.isArray(message.tool_calls)
			? (message.tool_calls as Array<Record<string, unknown>>)
			: [];
		const content = String(message.content ?? "");
		if (
			type === "ai" &&
			toolCalls.length === 0 &&
			normalizeText(content) &&
			!shouldHideStreamingInternalContent(content)
		) {
			visibleIndexesInTurn.push(index);
		}
	}

	closeTurn();
	return hidden;
}
