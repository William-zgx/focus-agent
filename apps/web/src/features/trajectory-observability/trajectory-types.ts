export type SortMode = "newest" | "latency" | "tool_calls";
export type StatusMode = "all" | "failed" | "succeeded";
export type PresetMode = "failures" | "fallback" | "latency" | "all";

export type FilterChip = {
	id: string;
	labelZh: string;
	labelEn: string;
	clear: () => void;
};

export type CorrelationSignal = {
	id: string;
	labelZh: string;
	labelEn: string;
	value: string;
	tone?: "neutral" | "accent";
};

export type EvidenceMode = "timeline" | "zero_step" | "missing_detail";

export type ReviewSummary = {
	headline: string;
	lead: string;
	status: string;
	createdAt: string;
	evidenceLabel: string;
	stats: Array<{
		id: string;
		labelZh: string;
		labelEn: string;
		value: string;
	}>;
};

export type ActionRailSection = {
	id: string;
	titleZh: string;
	titleEn: string;
	captionZh: string;
	captionEn: string;
	count?: string;
};
