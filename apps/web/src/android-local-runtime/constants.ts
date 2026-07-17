export const STORAGE_KEY = "focus-agent-android-local-runtime-state";
export const SECRET_STORAGE_KEY =
	"focus-agent-android-local-runtime-model-secrets";
export const SECRET_STORAGE_FALLBACK_KEY =
	"focus-agent-android-local-runtime-model-secrets-fallback";
export const LOCAL_USER_ID = "android-local-user";
export const LOCAL_TENANT_ID = "android-local";
export const LOCAL_RUNTIME_ACCESS_MODE = "device-local-single-user";
export const ANDROID_LOCAL_AUTH_UNSUPPORTED_MESSAGE =
	"Android local runtime is a device-local single-user mode and does not support account, password, token, or session authentication.";
export const ANDROID_LOCAL_ADMIN_UNSUPPORTED_MESSAGE =
	"Administrative and user-governance endpoints are unavailable in Android local single-user mode.";
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
	"workspace_tree",
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
