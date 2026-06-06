export interface TranscriptDisplayMessage {
	kind: "message";
	id: string;
	type: string;
	content: string;
	totalTokens?: number;
}

export interface ToolDetailEntry {
	id: string;
	label: string;
	content: string;
	language: string;
}

export type ProcessingStepTone = "neutral" | "warn" | "success" | "danger";

export interface ProcessingStepEntry {
	id: string;
	kind: "reasoning" | "tool" | "task" | "agent" | "skill";
	label: string;
	status: "pending" | "running" | "completed" | "failed";
	tone: ProcessingStepTone;
	content?: string;
	detail?: ToolDetailEntry;
}

export interface ToolActivityItem {
	kind: "tool-activity";
	id: string;
	skillIds: string[];
	toolNames: string[];
	summaryText: string;
	details: ToolDetailEntry[];
	steps: ProcessingStepEntry[];
}

export type TranscriptItem = TranscriptDisplayMessage | ToolActivityItem;
