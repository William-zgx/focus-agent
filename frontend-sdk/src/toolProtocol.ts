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
const INTERNAL_PROCESS_NARRATION_RE =
  /(?:^|[\n。；;:：])\s*(?:我(?:来|先)?(?:帮你|为你)?(?:查询|获取|搜索|查找)|先(?:获取|查询|搜索|抓取)|让我(?:先|再)?(?:尝试|查询|搜索|获取|访问|抓取)|现在让我|接下来我(?:会|将)?尝试|我(?:会|将|再)?尝试(?:通过)?)(?=.{0,160}(?:搜索|查询|访问|获取|抓取|页面|数据|行情|日线|东方财富|数据源|web_fetch|web_search|tool|fetch|search|browse|计算))/ims;
const INTERNAL_SEARCH_RESULT_NARRATION_RE =
  /(?:我已经|我已)(?:从|在).{0,12}搜索结果.{0,80}(?:获取|拿到|掌握|整理)/ims;
const INTERNAL_CONTINUATION_LOOP_RE =
  /(?=.{0,260}(?:获取|查询|搜索|执行|处理|分析|计划|数据|网页|页面|行情))(?:如果(?:你)?(?:没有|无)(?:进一步|额外|其他|特别|新的?)?(?:指示|要求|需求|回复)|如无(?:其他|额外|特别|新的?)?(?:要求|指示)|当前(?:继续|正在)(?:执行|处理|获取|分析)|我将(?:默认)?继续(?:执行|推进|处理)|请确认是否继续|如果没有回复|请稍候|正在(?:获取|查询|处理|分析)(?:数据)?)/ims;

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
  return (
    INTERNAL_PROCESS_NARRATION_RE.test(text) ||
    INTERNAL_SEARCH_RESULT_NARRATION_RE.test(text) ||
    INTERNAL_CONTINUATION_LOOP_RE.test(text)
  );
}

export function safeVisibleText(value: unknown): string {
  const text = typeof value === "string" ? value : "";
  return looksLikeTextualToolCallArtifact(text) ? "" : text;
}
