export const STORAGE_KEY = "focus-agent-android-local-runtime-state";
export const SECRET_STORAGE_KEY =
	"focus-agent-android-local-runtime-model-secrets";
export const SECRET_STORAGE_FALLBACK_KEY =
	"focus-agent-android-local-runtime-model-secrets-fallback";
export const LOCAL_USER_ID = "android-local-admin";
export const LOCAL_TENANT_ID = "android-local";
export const DEFAULT_PROVIDER_ID = "deepseek";
export const DEFAULT_PROVIDER_BASE_URL = "https://api.deepseek.com";
export const DEFAULT_MODEL_ID = "deepseek-v4-pro";
export const LOCAL_WEB_SEARCH_USER_AGENT =
	"FocusAgentAndroid/1.0 (+https://focus-agent.local)";

export const ANDROID_LOCAL_TOOL_NAMES = [
	"write_text_artifact",
	"artifact_list",
	"artifact_read",
	"artifact_update",
	"memory_save",
	"memory_search",
	"memory_forget",
	"conversation_summary",
	"skills_list",
	"skill_view",
	"skill_sources",
	"skills_search",
	"web_fetch",
	"web_search",
	"current_utc_time",
	"list_files",
	"read_file",
	"search_code",
	"codebase_stats",
	"apply_patch",
	"run_workspace_command",
	"git_status",
	"git_diff",
	"git_log",
	"skill_install",
	"skills_refresh_index",
] as const;

export const ANDROID_LOCAL_TOOL_NAME_SET = new Set<string>(
	ANDROID_LOCAL_TOOL_NAMES,
);

export const JSON_HEADERS = { "Content-Type": "application/json" };

export const SSE_HEADERS = {
	"Cache-Control": "no-cache",
	"Content-Type": "text/event-stream",
};
