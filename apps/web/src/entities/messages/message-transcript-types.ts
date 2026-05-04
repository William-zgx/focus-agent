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

export interface ToolActivityItem {
	kind: "tool-activity";
	id: string;
	toolNames: string[];
	summaryText: string;
	details: ToolDetailEntry[];
}

export type TranscriptItem = TranscriptDisplayMessage | ToolActivityItem;
