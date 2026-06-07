import type { LocalSkill } from "./types";
import { textWords } from "./local-text";

type SearchableLocalSkill = Pick<
	LocalSkill,
	| "skill_id"
	| "name"
	| "description"
	| "triggers"
	| "aliases"
	| "localized_triggers"
	| "domains"
	| "intents"
	| "when_to_use"
	| "primary_tools"
	| "recommended_tools"
>;

function uniqueStrings(values: unknown[]): string[] {
	return [
		...new Set(
			values
				.filter((value): value is string => typeof value === "string")
				.map((value) => value.trim())
				.filter(Boolean),
		),
	];
}

export function localSkillSearchTerms(skill: SearchableLocalSkill): string[] {
	return uniqueStrings([
		skill.skill_id,
		skill.name,
		skill.description,
		...skill.triggers,
		...(skill.aliases ?? []),
		...(skill.localized_triggers ?? []),
		...(skill.domains ?? []),
		...(skill.intents ?? []),
		...skill.when_to_use,
		...(skill.primary_tools ?? []),
		...skill.recommended_tools,
	]);
}

export function localSkillActivationTerms(skill: SearchableLocalSkill): string[] {
	return uniqueStrings([
		skill.skill_id,
		skill.name,
		...skill.triggers,
		...(skill.aliases ?? []),
		...(skill.localized_triggers ?? []),
		...(skill.domains ?? []),
		...(skill.intents ?? []),
	]);
}

export function localSkillMatchedTerms(
	skill: SearchableLocalSkill,
	query: string,
): string[] {
	return matchedTermsFor(localSkillSearchTerms(skill), query);
}

export function localSkillActivationMatchedTerms(
	skill: SearchableLocalSkill,
	query: string,
): string[] {
	return matchedTermsFor(localSkillActivationTerms(skill), query);
}

function matchedTermsFor(terms: string[], query: string): string[] {
	const queryWords = textWords(query);
	if (!queryWords.length) return [];
	return terms.filter((term) => {
		const normalizedTerm = term.toLowerCase();
		const termWords = new Set(textWords(term));
		return queryWords.some(
			(word) => termWords.has(word) || normalizedTerm.includes(word),
		);
	});
}

export function localSkillScore(
	skill: SearchableLocalSkill,
	query: string,
): number {
	return scoreTerms(localSkillSearchTerms(skill), query);
}

export function localSkillActivationScore(
	skill: SearchableLocalSkill,
	query: string,
): number {
	return scoreTerms(localSkillActivationTerms(skill), query);
}

function scoreTerms(terms: string[], query: string): number {
	const queryWords = textWords(query);
	if (!queryWords.length) return 1;
	const haystackWords = new Set(textWords(terms.join(" ")));
	return (
		queryWords.filter((word) => haystackWords.has(word)).length /
		queryWords.length
	);
}

export const ANDROID_LOCAL_SKILLS: LocalSkill[] = [
	{
		skill_id: "android-local-runtime",
		name: "android-local-runtime",
		description:
			"Run Focus Agent chat, admin, branches, and tools inside the Android app.",
		triggers: ["android", "mobile", "local runtime"],
		aliases: ["Android", "local", "本地运行时"],
		localized_triggers: ["安卓:", "本地:"],
		domains: ["mobile", "runtime"],
		intents: ["local app support", "runtime explanation"],
		when_to_use: [
			"The user wants to understand what the Android app can do without a Focus Agent backend.",
		],
		primary_tools: ["conversation_summary"],
		recommended_tools: ["conversation_summary", "web_search", "memory_search"],
		prompt_mode: "answer",
		content:
			"Use local app state first. Do not claim access to a Focus Agent backend, workspace shell, or Git checkout.",
		source_id: "android-local",
	},
	{
		skill_id: "branch-focus-score",
		name: "branch-focus-score",
		description: "Explain and use local Focus Score branch recommendations.",
		triggers: ["branch", "focus score", "推荐分支", "分支"],
		aliases: ["focus score", "推荐分支", "分支建议"],
		localized_triggers: ["分支:", "推荐分支:"],
		domains: ["branching", "conversation management"],
		intents: ["topic drift analysis", "branch recommendation"],
		when_to_use: [
			"The user asks whether a turn should continue current context or branch.",
		],
		primary_tools: ["conversation_summary"],
		recommended_tools: ["conversation_summary"],
		prompt_mode: "answer",
		content:
			"Use the Android local Focus Score decision and pending branch action when topic drift is detected.",
		source_id: "android-local",
	},
	{
		skill_id: "local-artifacts-memory",
		name: "local-artifacts-memory",
		description: "Use app-local artifacts and durable local memory.",
		triggers: ["artifact", "memory", "产物", "记忆"],
		aliases: ["artifact", "memory", "产物", "记忆"],
		localized_triggers: ["产物:", "记忆:"],
		domains: ["artifacts", "memory"],
		intents: ["save local information", "read local artifacts"],
		when_to_use: [
			"The user asks to save, read, update, remember, search, or forget local information.",
		],
		primary_tools: ["memory_search"],
		recommended_tools: [
			"write_text_artifact",
			"artifact_list",
			"memory_save",
			"memory_search",
		],
		prompt_mode: "execute",
		content:
			"Persist only app-local artifacts and memories. Keep productivity notes/tasks out of Android.",
		source_id: "android-local",
	},
	{
		skill_id: "local-web-tools",
		name: "local-web-tools",
		description:
			"Search or fetch public web content directly from the Android app.",
		triggers: ["web", "search", "fetch", "网页搜索", "抓取"],
		aliases: ["web", "search", "网页", "联网", "搜索"],
		localized_triggers: ["网页:", "搜索:"],
		domains: ["web", "current information"],
		intents: ["web search", "URL fetch", "current time lookup"],
		when_to_use: [
			"The user asks for current, recent, online, or URL-specific information.",
		],
		primary_tools: ["web_search"],
		recommended_tools: ["current_utc_time", "web_search", "web_fetch"],
		prompt_mode: "execute",
		content:
			"Use current_utc_time for temporal queries, web_search for open lookup, and web_fetch for a specific URL.",
		source_id: "android-local",
	},
];
