const TEXTUAL_TOOL_ARTIFACT_MARKERS = [
  "function_calls",
  "invoke name=",
  "<｜dsml｜",
  "tool-observation://",
  "tool-result://",
  "<tool_c",
  "</tool_c",
  "<tool_call",
  "<tool_calls",
  "</tool_call",
  "</tool_calls",
  "<invoke=",
  "</invoke>",
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

const BRACKET_TOOL_MARKER_RE =
  /(?:^|[\s"'*_`>])\[([A-Za-z_][\w.-]*)\](?=$|[\s"'*_`<:：).,，。-])/gm;
const DSML_TOKEN_RE = /<\s*\/?\s*(?:[|｜]\s*){1,2}dsml\s*(?:[|｜]\s*){1,2}/ims;
const BARE_DSML_TOKEN_RE = /(?:^|[\s</])(?:[|｜]\s*){1,2}dsml\s*(?:[|｜]\s*){1,2}/ims;
const DSML_TOOL_MARKUP_RE =
  /(?:^|[\n\r<|｜/])\s*(?:[-*•·]\s*)*\/?<?\s*(?:invoke\s+name(?:\b|[A-Za-z0-9_"'=])[^<>\n]{0,160}|parameter\s+name(?:\b|[A-Za-z0-9_"'=])[^<>\n]{0,240}|tool_?calls\s*(?:>|\/))/ims;
const XMLISH_TOOL_CALL_RE =
  /<\s*\/?\s*tool_?c(?:alls?)?\s*>|<\s*\/?\s*invoke(?:\s*=|\s+name\b|>)|<\s*\/?\s*parameter(?:[\w.-]+|\s+name\b|\s*=|>)|(?:^|[\s<])\/?<?function\s*=\s*[a-z_][\w.-]*\s*>|(?:^|[\n\r<|｜/])\s*(?:[-*•·]\s*)*\/?<?invoke\s+name(?:\b|[A-Za-z0-9_"'=])[^<>\n]{0,160}|<\s*\/?\s*parameter\s*=|<[^>\n]{0,120}\bparameter\s+name\s*=|(?:^|[\s<])\/?<?parameter\s*=\s*[\w.-]+\s*>/ims;
const DEGRADED_TOOL_PROTOCOL_FRAGMENT_RE =
  /(?:^|[\n\r])\s*(?:(?:alls?|calls?|tool_?calls?|invoke|parameter)>|(?:https?:\/\/[^\s<>"']{1,240}|[0-9]{1,8}|[a-z_][\w.-]{0,80})\s*(?:parameter|invoke)>|=\s*["']?(?:web_[a-z_]+|[a-z_]*(?:chars?|url|query|count|fresh_days|format|limit|length|path|filepath|read|max_results)[\w.-]*)["']?(?:\s*=|\s+string\s*=?|\s+string(?:true|false)|["']\s*(?:string|true|false|>|[0-9])|>)|=\s*["'][^"'\n]{1,160}["']\s*(?:>|string\s*=)|<\/?\s*(?:invoke|tool_?c|tool_?calls?|parameter)\s*>)/ims;
const TOOL_RESULT_URI_RE =
  /\b(?:tool[-_](?:observation|result|call|calls)|toolcall|observation):\/\/[^\s<>"']+/ims;
const DEGRADED_PARAMETER_TAIL_RE =
  /(?:^|[\n\r])\s*=\s*["']?[\w.-]{1,80}(?:=\s*["']?[\w.-]{1,80})?["']?\s+(?:string|number|boolean|object|array)\s*=?\s*["']?(?:true|false)?["']?\s*>|(?:^|[\n\r])\s*=\s*["']?[\w.-]{1,80}(?:=\s*["']?[\w.-]{1,80})?["']?\s*(?:true|false|null|[0-9]{1,8})?\s*>|(?:^|[\n\r])\s*=\s*["']?[\w.-]{1,80}(?:=\s*["']?[\w.-]{1,80})?["']?\s*(?:string|number|boolean|object|array)?\s*(?:true|false|null)?[0-9]{0,8}\s*(?:parameter|invoke)>/ims;
const TOOL_CALL_PREFIX_RE =
  /^\s*(?:https?:\/\/[^\s<>"']{1,512}|<|<\/|<\/<|<\s*\/?\s*(?:t|to|too|tool|tool_|tool_?c|tool_?ca|tool_?cal|tool_?call|tool_?calls?)|<\s*\/?\s*(?:i|in|inv|invo|invok|invoke)(?:\s*=)?|<\s*\/?\s*(?:p|pa|par|para|param|parame|paramet|paramete|parameter)(?:[\w.-]*|\s*=)?|<\s*\/?\s*(?:[|｜]\s*){0,2}(?:d|ds|dsm|dsml)?\s*(?:[|｜]\s*){0,2}|=|=\s*["']?[\w.-]*(?:=\s*["']?[\w.-]*)?["']?(?:\s*(?:t|tr|tru|true|f|fa|fal|fals|false|n|nu|null|[0-9]{1,8})|\s+(?:s|st|str|string|n|nu|num|numb|numbe|number|b|bo|boo|bool|boole|boolea|boolean|o|ob|obj|obje|objec|object|a|ar|arr|arra|array)(?:\s*=?)?)?|f|fu|fun|func|funct|functi|functio|function(?:\s*=\s*[\w.-]*)?|i|in|inv|invo|invok|invoke(?:\s+n(?:a(?:m(?:e)?)?)?)?|p|pa|par|para|param|parame|paramet|paramete|parameter(?:\s*=\s*[\w.-]*)?|t|to|too|tool|tool_?c|tool_?ca|tool_?cal|tool_?call|tool_?calls\/?|tool-|tool-o|tool-ob|tool-obs|tool-obse|tool-obser|tool-observ|tool-observa|tool-observat|tool-observati|tool-observatio|tool-observation(?::\/?)?)$/i;
const INTERNAL_PROCESS_NARRATION_RE =
  /(?:^|[\n。；;:：,，])\s*(?:我(?:来|先)?(?:帮你|为你)?(?:查询|获取|搜索|查找)|先(?:获取|查询|搜索|抓取)|让我(?:先|再)?(?:尝试|查询|搜索|获取|访问|抓取)|让我(?:先|再|进一步)?(?:查询|搜索|获取|访问|抓取)|现在让我|接下来我(?:会|将)?尝试|我(?:会|将|再)?尝试(?:通过)?)(?=.{0,160}(?:搜索|查询|访问|获取|抓取|页面|来源|资料|信息|内容|数据|行情|日线|东方财富|数据源|web_fetch|web_search|tool|fetch|search|browse|计算))/ims;
const INTERNAL_SEARCH_RESULT_NARRATION_RE =
  /(?:我已经|我已)(?:从|在).{0,12}搜索结果.{0,80}(?:获取|拿到|掌握|整理)/ims;
const INTERNAL_CONTINUATION_LOOP_RE =
  /(?=.{0,260}(?:获取|查询|搜索|执行|处理|分析|计划|数据|网页|页面|行情))(?:如果(?:你)?(?:没有|无)(?:进一步|额外|其他|特别|新的?)?(?:指示|要求|需求|回复)|如无(?:其他|额外|特别|新的?)?(?:要求|指示)|当前(?:继续|正在)(?:执行|处理|获取|分析)|我将(?:默认)?继续(?:执行|推进|处理)|请确认是否继续|如果没有回复|请稍候|正在(?:获取|查询|处理|分析)(?:数据)?)/ims;
const INTERNAL_TOOL_DELIBERATION_RE =
  /(?=.{0,360}(?:web[_\s-]?search|web[_\s-]?fetch|工具|tool|搜索结果))(?:我(?:因为|之前|刚才).{0,180}(?:搜索结果|重复调用|工具|web[_\s-]?search|web[_\s-]?fetch)|我(?:现在|直接|将|会|需要|必须|要).{0,120}(?:执行|调用).{0,120}(?:web[_\s-]?search|web[_\s-]?fetch|工具|tool|搜索|抓取|获取)|(?:这是不对的|不应该这样|不再重复调用).{0,180}(?:执行|调用|工具|web[_\s-]?search|web[_\s-]?fetch)|现在我(?:直接)?执行\s*[:：]|(?:搜索结果).{0,120}(?:犹豫|重复调用|不满意))/ims;
const INTERNAL_TOOL_DELIBERATION_PREFIX_RE =
  /^\s*(?:我|我因|我因为|我之|我之前|我刚|我刚才|现在我|现在我直|现在我直接|现在我直接执|现在我直接执行|这是|这是不|这是不对|这是不对的|不再|不再重复|搜索结果|搜|搜索)$/is;
const INTERNAL_TOOL_REFERENCE_FRAGMENT_RE =
  /^\s*(?:和|与|及|、|,|，)?\s*web[_\s-]?(?:search|fetch)\s*[。.,，;；]?\s*$/is;
const INTERNAL_ENGLISH_PROCESS_NARRATION_RE =
  /^\s*(?:let\s+me(?:\s+\w+){0,8}\s+(?:fetch|search|look|browse|check|inspect|open|query|calculate|use|call|try|produce\s+(?:the\s+)?final\s+answer|draft\s+(?:the\s+)?final\s+answer|write\s+(?:the\s+)?final\s+answer)|i\s+(?:should|need\s+to|will|can|am\s+going\s+to|must|have\s+to)\s+(?:fetch|search|look|browse|check|inspect|open|query|calculate|use|call|try|continue|retry)|i\s+must\s+not\s+call\s+more\s+tools|wait(?:,|\b).{0,160}(?:tool|fetch|search|look|browse|check|need|should|actually|final)|(?:analysis|assistant\s+final|final\s+answer)\s*[:：]\s*(?:$|<|```|tool|function))/ims;
const INTERNAL_FINAL_ANSWER_BOUNDARY_RE =
  /\b(?:let['’]s\s+go|final\s+answer|assistant\s+final|here(?:'s|\s+is)\s+(?:the\s+)?(?:final\s+)?answer)\s*[:：.\-]*\s*/gis;
const INTERNAL_FINAL_ANSWER_UNSAFE_SUFFIX_RE =
  /^\s*(?:tool\b|function\b|call\b|invoke\b|parameter\b|tool_?calls?\b|<|```)/is;

type ToolProtocolTextState = "visible" | "internal" | "pending";

function normalizedProtocolText(value: unknown): string {
  return String(value ?? "").trim().toLowerCase();
}

function looksLikeKnownToolMarker(text: string, knownToolNames?: Iterable<string>): boolean {
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

function looksLikeStructuredToolProtocol(text: string): boolean {
  return (
    DSML_TOKEN_RE.test(text) ||
    BARE_DSML_TOKEN_RE.test(text) ||
    DSML_TOOL_MARKUP_RE.test(text) ||
    XMLISH_TOOL_CALL_RE.test(text)
  );
}

function looksLikeDegradedToolProtocol(text: string): boolean {
  return (
    DEGRADED_TOOL_PROTOCOL_FRAGMENT_RE.test(text) ||
    DEGRADED_PARAMETER_TAIL_RE.test(text) ||
    TOOL_RESULT_URI_RE.test(text)
  );
}

function looksLikeToolCallRecord(value: unknown, knownToolNames?: Iterable<string>): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  const name =
    typeof record.name === "string"
      ? record.name
      : typeof (record.function as Record<string, unknown> | undefined)?.name === "string"
        ? String((record.function as Record<string, unknown>).name)
        : "";
  const normalizedName = name.trim().toLowerCase();
  if (!normalizedName) {
    return false;
  }
  const toolNames = new Set(DEFAULT_TEXTUAL_TOOL_NAMES);
  for (const knownName of knownToolNames ?? []) {
    const normalized = String(knownName).trim().toLowerCase();
    if (normalized) {
      toolNames.add(normalized);
    }
  }
  const hasArgs =
    "args" in record ||
    "arguments" in record ||
    "input" in record ||
    Boolean((record.function as Record<string, unknown> | undefined)?.arguments);
  return hasArgs || toolNames.has(normalizedName);
}

function looksLikeStructuredToolCallJson(value: unknown, knownToolNames?: Iterable<string>): boolean {
  const text = String(value ?? "").trim();
  if (!text || (!text.startsWith("{") && !text.startsWith("["))) {
    return false;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return false;
  }

  function visit(node: unknown, depth: number): boolean {
    if (depth > 4 || node === null || node === undefined) {
      return false;
    }
    if (Array.isArray(node)) {
      return node.some((item) => visit(item, depth + 1));
    }
    if (typeof node !== "object") {
      return false;
    }
    const record = node as Record<string, unknown>;
    if (Array.isArray(record.tool_calls) || Array.isArray(record.toolCalls)) {
      return true;
    }
    if (
      record.function_call ||
      record.functionCall ||
      record.tool_call ||
      record.toolCall
    ) {
      return true;
    }
    if (looksLikeToolCallRecord(record, knownToolNames)) {
      return true;
    }
    return false;
  }

  return visit(parsed, 0);
}

function looksLikeEnglishProcessNarration(text: string): boolean {
  return INTERNAL_ENGLISH_PROCESS_NARRATION_RE.test(text);
}

function suffixAfterInternalFinalAnswerBoundary(text: string): string {
  INTERNAL_FINAL_ANSWER_BOUNDARY_RE.lastIndex = 0;
  let lastSuffix = "";
  let match = INTERNAL_FINAL_ANSWER_BOUNDARY_RE.exec(text);
  while (match) {
    const suffix = text.slice(match.index + match[0].length).replace(/^[.…\s]+/, "");
    if (suffix) {
      lastSuffix = suffix;
    }
    match = INTERNAL_FINAL_ANSWER_BOUNDARY_RE.exec(text);
  }
  return lastSuffix;
}

function sanitizeProtocolVisibleText(value: unknown, knownToolNames?: Iterable<string>): string {
  const originalText = typeof value === "string" ? value : "";
  if (!originalText.trim()) {
    return "";
  }
  const text = normalizedProtocolText(originalText);
  if (
    looksLikeKnownToolMarker(text, knownToolNames) ||
    looksLikeStructuredToolProtocol(text) ||
    looksLikeDegradedToolProtocol(text) ||
    looksLikeStructuredToolCallJson(originalText, knownToolNames) ||
    INTERNAL_PROCESS_NARRATION_RE.test(text) ||
    INTERNAL_SEARCH_RESULT_NARRATION_RE.test(text) ||
    INTERNAL_CONTINUATION_LOOP_RE.test(text) ||
    INTERNAL_TOOL_DELIBERATION_RE.test(text) ||
    INTERNAL_TOOL_REFERENCE_FRAGMENT_RE.test(text)
  ) {
    return "";
  }
  if (!looksLikeEnglishProcessNarration(originalText)) {
    return originalText;
  }

  const suffix = suffixAfterInternalFinalAnswerBoundary(originalText);
  if (!suffix) {
    return "";
  }
  const normalizedSuffix = normalizedProtocolText(suffix);
  if (
    looksLikeKnownToolMarker(normalizedSuffix, knownToolNames) ||
    looksLikeStructuredToolProtocol(normalizedSuffix) ||
    looksLikeDegradedToolProtocol(normalizedSuffix) ||
    looksLikeStructuredToolCallJson(suffix, knownToolNames) ||
    INTERNAL_FINAL_ANSWER_UNSAFE_SUFFIX_RE.test(suffix) ||
    looksLikeEnglishProcessNarration(suffix) ||
    INTERNAL_PROCESS_NARRATION_RE.test(normalizedSuffix) ||
    INTERNAL_SEARCH_RESULT_NARRATION_RE.test(normalizedSuffix) ||
    INTERNAL_CONTINUATION_LOOP_RE.test(normalizedSuffix) ||
    INTERNAL_TOOL_DELIBERATION_RE.test(normalizedSuffix) ||
    INTERNAL_TOOL_REFERENCE_FRAGMENT_RE.test(normalizedSuffix)
  ) {
    return "";
  }
  return suffix;
}

function classifyToolProtocolText(
  value: unknown,
  knownToolNames?: Iterable<string>,
): ToolProtocolTextState {
  const originalText = typeof value === "string" ? value : String(value ?? "");
  const text = normalizedProtocolText(originalText);
  if (!text) {
    return "visible";
  }
  if (
    looksLikeKnownToolMarker(text, knownToolNames) ||
    looksLikeStructuredToolProtocol(text) ||
    looksLikeDegradedToolProtocol(text) ||
    looksLikeStructuredToolCallJson(originalText, knownToolNames) ||
    INTERNAL_PROCESS_NARRATION_RE.test(text) ||
    INTERNAL_SEARCH_RESULT_NARRATION_RE.test(text) ||
    INTERNAL_CONTINUATION_LOOP_RE.test(text) ||
    INTERNAL_TOOL_DELIBERATION_RE.test(text) ||
    INTERNAL_TOOL_REFERENCE_FRAGMENT_RE.test(text) ||
    sanitizeProtocolVisibleText(originalText, knownToolNames) !== originalText
  ) {
    return "internal";
  }
  if (looksLikePotentialTextualToolCallPrefix(text)) {
    return "pending";
  }
  return "visible";
}

export function looksLikeTextualToolCallArtifact(
  value: unknown,
  knownToolNames?: Iterable<string>,
): boolean {
  return classifyToolProtocolText(value, knownToolNames) === "internal";
}

export function safeVisibleText(value: unknown): string {
  return sanitizeProtocolVisibleText(value);
}

function looksLikePotentialTextualToolCallPrefix(value: unknown): boolean {
  const text = String(value ?? "").trim();
  if (!text || text.length > 512) {
    return false;
  }
  return (
    TOOL_CALL_PREFIX_RE.test(text) ||
    INTERNAL_TOOL_DELIBERATION_PREFIX_RE.test(text)
  );
}

export function safeVisibleTextTransition(
  currentText: string,
  value: unknown,
  pendingText = "",
): { visibleText: string; pendingText: string } {
  const delta = typeof value === "string" ? value : "";
  if (!delta) {
    return { visibleText: currentText, pendingText };
  }

  const candidatePending = `${pendingText}${delta}`;
  const candidateVisible = `${currentText}${candidatePending}`;
  const pendingState = classifyToolProtocolText(candidatePending);
  const visibleState = classifyToolProtocolText(candidateVisible);
  if (pendingState === "internal" || visibleState === "internal") {
    const safePending = safeVisibleText(candidatePending);
    if (safePending) {
      return { visibleText: currentText + safePending, pendingText: "" };
    }
    if (!currentText) {
      const safeVisible = safeVisibleText(candidateVisible);
      if (safeVisible) {
        return { visibleText: safeVisible, pendingText: "" };
      }
    }
    const currentLooksInternal =
      looksLikeTextualToolCallArtifact(currentText) ||
      looksLikePotentialTextualToolCallPrefix(currentText);
    return { visibleText: currentLooksInternal ? "" : currentText, pendingText: "" };
  }

  if (pendingState === "pending") {
    return { visibleText: currentText, pendingText: candidatePending };
  }

  return {
    visibleText: currentText + safeVisibleText(candidatePending),
    pendingText: "",
  };
}
