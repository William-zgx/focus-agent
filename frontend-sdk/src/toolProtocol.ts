const TEXTUAL_TOOL_ARTIFACT_MARKERS = [
  "function_calls",
  "invoke name=",
  "<｜dsml｜",
  "<tool_call",
  '"tool_name"',
];

const DEFAULT_TEXTUAL_TOOL_NAMES = new Set([
  "artifact_list",
  "artifact_read",
  "codebase_stats",
  "conversation_summary",
  "current_utc_time",
  "git_diff",
  "git_log",
  "git_status",
  "list_files",
  "read_file",
  "search_code",
  "skills_list",
  "skill_view",
  "web_fetch",
  "web_search",
  "write_text_artifact",
]);

const BRACKET_TOOL_MARKER_RE = /^\s*\[([A-Za-z_][\w.-]*)\]\s*/gm;

export function looksLikeTextualToolCallArtifact(
  value: unknown,
  knownToolNames?: Iterable<string>,
): boolean {
  const text = String(value ?? "").trim().toLowerCase();
  if (!text) {
    return false;
  }
  if (TEXTUAL_TOOL_ARTIFACT_MARKERS.some((marker) => text.includes(marker))) {
    return true;
  }

  const toolNames = new Set(DEFAULT_TEXTUAL_TOOL_NAMES);
  for (const name of knownToolNames ?? []) {
    const normalized = String(name).trim().toLowerCase();
    if (normalized) {
      toolNames.add(normalized);
    }
  }

  BRACKET_TOOL_MARKER_RE.lastIndex = 0;
  for (const match of text.matchAll(BRACKET_TOOL_MARKER_RE)) {
    if (toolNames.has(match[1].toLowerCase())) {
      return true;
    }
  }
  return false;
}

export function safeVisibleText(value: unknown): string {
  const text = typeof value === "string" ? value : "";
  return looksLikeTextualToolCallArtifact(text) ? "" : text;
}
