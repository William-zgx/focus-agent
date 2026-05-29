import type { LocalSkill } from "./types";

export const ANDROID_LOCAL_SKILLS: LocalSkill[] = [
	{
		skill_id: "android-local-runtime",
		name: "android-local-runtime",
		description:
			"Run Focus Agent chat, admin, branches, and tools inside the Android app.",
		triggers: ["android", "mobile", "local runtime"],
		when_to_use: [
			"The user wants to understand what the Android app can do without a Focus Agent backend.",
		],
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
		when_to_use: [
			"The user asks whether a turn should continue current context or branch.",
		],
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
		when_to_use: [
			"The user asks to save, read, update, remember, search, or forget local information.",
		],
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
		when_to_use: [
			"The user asks for current, recent, online, or URL-specific information.",
		],
		recommended_tools: ["current_utc_time", "web_search", "web_fetch"],
		prompt_mode: "execute",
		content:
			"Use current_utc_time for temporal queries, web_search for open lookup, and web_fetch for a specific URL.",
		source_id: "android-local",
	},
];
