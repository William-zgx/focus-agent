import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { TextEncoder, TextDecoder } from "node:util";
import vm from "node:vm";
import { pathToFileURL } from "node:url";

const repoRoot = process.cwd();
const typescriptModuleUrl = pathToFileURL(
  path.join(repoRoot, "apps/web/node_modules/typescript/lib/typescript.js"),
).href;
const ts = await import(typescriptModuleUrl);

function compactSource(sourceText) {
  return sourceText.split(/\s+/u).join(" ");
}

function readCssModule(relativePath, seen = new Set()) {
  const normalizedPath = relativePath.replaceAll(path.sep, "/");
  if (seen.has(normalizedPath)) {
    return "";
  }
  seen.add(normalizedPath);
  const absolutePath = path.join(repoRoot, normalizedPath);
  const sourceText = readFileSync(absolutePath, "utf8");
  const relativeDir = path.dirname(normalizedPath);
  return sourceText.replace(/@import\s+["'](.+?)["'];/gu, (_match, importPath) =>
    readCssModule(path.join(relativeDir, importPath), seen),
  );
}

function extractFunction(sourceText, functionName) {
  const signature = new RegExp(`(?:export\\s+)?function\\s+${functionName}\\s*\\(`);
  const start = sourceText.search(signature);
  if (start === -1) {
    throw new Error(`Function ${functionName} not found`);
  }

  let braceDepth = 0;
  let bodyStarted = false;
  let inString = false;
  let stringQuote = "";
  let previous = "";

  for (let index = start; index < sourceText.length; index += 1) {
    const char = sourceText[index];
    if (inString) {
      if (char === stringQuote && previous !== "\\") {
        inString = false;
        stringQuote = "";
      }
      previous = char;
      continue;
    }

    if (char === '"' || char === "'" || char === "`") {
      inString = true;
      stringQuote = char;
      previous = char;
      continue;
    }

    if (char === "{") {
      braceDepth += 1;
      bodyStarted = true;
    } else if (char === "}") {
      braceDepth -= 1;
      if (bodyStarted && braceDepth === 0) {
        return sourceText.slice(start, index + 1);
      }
    }
    previous = char;
  }

  throw new Error(`Function ${functionName} is missing a closing brace`);
}

function loadFunctions(relativePath, functionNames) {
  const sourceText = readFileSync(path.join(repoRoot, relativePath), "utf8");
  const snippets = functionNames.map((name) => extractFunction(sourceText, name));
  if (!functionNames.includes("hasOwn") && snippets.join("\n").includes("hasOwn(")) {
    snippets.unshift(extractFunction(sourceText, "hasOwn"));
  }
  const snippet = snippets.join("\n\n");
  const transpiled = ts.transpileModule(snippet, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;

  const context = {
    exports: {},
    module: { exports: {} },
  };
  vm.runInNewContext(`${transpiled}\nmodule.exports = { ${functionNames.join(", ")} };`, context);
  return context.module.exports;
}

function loadModule(relativePath) {
	const sourceText = readFileSync(path.join(repoRoot, relativePath), "utf8");
	const transpiled = ts.transpileModule(sourceText, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const moduleExports = {};
  const context = {
    exports: moduleExports,
    module: { exports: moduleExports },
    TextDecoder,
  };
	vm.runInNewContext(transpiled, context);
	return context.module.exports;
}

function loadThreadBusyRetryModule() {
  const sourceText = readFileSync(
    path.join(repoRoot, "apps/web/src/shared/thread/retry-thread-busy-conflict.ts"),
    "utf8",
  );
  const transpiled = ts.transpileModule(sourceText, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  class FocusAgentRequestError extends Error {
    constructor(message, { status = 500, data = null } = {}) {
      super(message);
      this.name = "FocusAgentRequestError";
      this.status = status;
      this.data = data;
    }
  }
  const moduleExports = {};
  const context = {
    exports: moduleExports,
    module: { exports: moduleExports },
    require(moduleName) {
      if (moduleName === "@focus-agent/web-sdk") {
        return { FocusAgentRequestError };
      }
      throw new Error(`Unexpected module import: ${moduleName}`);
    },
    setTimeout(callback) {
      callback();
      return 0;
    },
  };
  vm.runInNewContext(transpiled, context);
  return { ...context.module.exports, FocusAgentRequestError };
}

function loadMessageComposerSubmitModule() {
  const sourceText = readFileSync(
    path.join(repoRoot, "apps/web/src/features/thread-stream/message-composer-submit.ts"),
    "utf8",
  );
  const transpiled = ts.transpileModule(sourceText, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const moduleExports = {};
  const context = {
    exports: moduleExports,
    module: { exports: moduleExports },
    require(moduleName) {
      if (moduleName === "./message-composer-helpers") {
        return { thinkingModeRequestValueForModel: () => "auto" };
      }
      throw new Error(`Unexpected module import: ${moduleName}`);
    },
  };
  vm.runInNewContext(transpiled, context);
  return context.module.exports;
}

function loadSdkStreamFunctions() {
  const toolProtocolSource = readFileSync(
    path.join(repoRoot, "frontend-sdk/src/toolProtocol.ts"),
    "utf8",
  );
  const reducersSource = readFileSync(
    path.join(repoRoot, "frontend-sdk/src/reducers.ts"),
    "utf8",
  );
  const functionNames = [
    "looksLikeTextualToolCallArtifact",
    "safeVisibleText",
    "createInitialStreamState",
    "reduceStreamEvent",
  ];
  const reducerSnippet = [
    "createInitialStreamState",
    "stringValue",
    "stringifyValue",
    "compactText",
    "namespaceKey",
    "upsertProcessingStep",
    "stepStatusForTask",
    "stepStatusForToolEvent",
    "toolNameForEvent",
    "toolStepIdForEvent",
    "upsertReasoningStep",
    "upsertToolCallStep",
    "upsertToolLifecycleStep",
    "upsertTaskStep",
    "failOpenProcessingSteps",
    "applyVisibleTextDelta",
    "applyVisibleTextCompleted",
    "applyReasoningDelta",
    "reduceStreamEvent",
  ]
    .map((name) => extractFunction(reducersSource, name))
    .join("\n\n");
  const transpiled = ts.transpileModule(`${toolProtocolSource}\n\n${reducerSnippet}`, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const context = {
    exports: {},
    module: { exports: {} },
  };
  vm.runInNewContext(`${transpiled}\nmodule.exports = { ${functionNames.join(", ")} };`, context);
  return context.module.exports;
}

function loadMessageTranscriptFunctions() {
  const toolProtocolSource = readFileSync(
    path.join(repoRoot, "frontend-sdk/src/toolProtocol.ts"),
    "utf8",
  );
  const sources = [
    readFileSync(
      path.join(repoRoot, "apps/web/src/entities/messages/message-transcript-normalize.ts"),
      "utf8",
    ),
    readFileSync(
      path.join(repoRoot, "apps/web/src/entities/messages/message-transcript-tool-summary.ts"),
      "utf8",
    ),
    readFileSync(
      path.join(repoRoot, "apps/web/src/entities/messages/message-transcript-visibility.ts"),
      "utf8",
    ),
    readFileSync(
      path.join(repoRoot, "apps/web/src/entities/messages/message-transcript-builder.ts"),
      "utf8",
    ),
  ].join("\n\n");
  const functionNames = [
    "normalizeMessageType",
    "normalizeText",
    "parseJsonValue",
    "totalTokensFromUsageMetadata",
    "truncateText",
    "extractToolSummaryCandidate",
    "summarizeToolResult",
    "formatToolDetailContent",
    "uniqueToolNames",
    "looksLikeInternalToolMarkup",
    "looksLikeToolPlanningPayload",
    "shouldHideStreamingInternalContent",
    "visibleAssistantIndexesToHide",
    "appendUniqueValues",
    "recordValue",
    "arrayValue",
    "stringListValue",
    "parsedJsonLikeValue",
    "collectSkillIdsFromMetadata",
    "collectSkillIdsFromRecordMetadata",
    "turnMetadataFromMessage",
    "hasSkillExecutionMetadata",
    "skillExecutionPlanContent",
    "executionContractContent",
    "contractTone",
    "contractStepStatus",
    "skillIdFromSkillPath",
    "collectSkillIdsFromCwd",
    "collectSkillIdsFromSkillPayload",
    "buildTranscriptItems",
  ];
  const snippet = functionNames.map((name) => extractFunction(sources, name)).join("\n\n");
  const transpiled = ts.transpileModule(
    `${toolProtocolSource}\n\n${snippet}`,
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText;
  const context = {
    exports: {},
    module: { exports: {} },
  };
  vm.runInNewContext(`${transpiled}\nmodule.exports = { buildTranscriptItems, totalTokensFromUsageMetadata };`, context);
  return context.module.exports;
}

function loadTrajectoryUtilityFunctions() {
  const sourceText = readFileSync(
    path.join(repoRoot, "apps/web/src/features/trajectory-observability/trajectory-formatters.ts"),
    "utf8",
  );
  const functionNames = [
    "visiblePreviewText",
    "extractStructuredSummary",
    "compactSnippet",
  ];
  const snippet = functionNames.map((name) => extractFunction(sourceText, name)).join("\n\n");
  const transpiled = ts.transpileModule(
    `function safeVisibleText(value) {
      const text = String(value ?? "");
      return text.includes("<｜DSML｜") || text.includes("invoke name=") || text.includes("[web_fetch]")
        ? ""
        : text;
    }
    ${snippet}`,
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText;
  const context = {
    exports: {},
    module: { exports: {} },
  };
  vm.runInNewContext(
    `${transpiled}\nmodule.exports = { extractStructuredSummary, compactSnippet };`,
    context,
  );
  return context.module.exports;
}

function loadMarkdownParagraphFunction() {
  const sourceText = readFileSync(
    path.join(repoRoot, "apps/web/src/entities/messages/message-markdown-blocks.tsx"),
    "utf8",
  );
  const snippet = extractFunction(sourceText, "paragraphNode");
  const transpiled = ts.transpileModule(snippet, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React,
    },
  }).outputText;
  const context = {
    exports: {},
    module: { exports: {} },
    React: {
      createElement(type, props, ...children) {
        return {
          type,
          key: props?.key ?? null,
          props: { ...(props ?? {}), children },
        };
      },
    },
    Fragment: Symbol.for("react.fragment"),
    inlineNodes(line, key) {
      return [{ line, key }];
    },
  };
  vm.runInNewContext(`${transpiled}\nmodule.exports = { paragraphNode };`, context);
  return context.module.exports.paragraphNode;
}

test("request cleanup clears the optimistic user message after failed sends", () => {
	const {
		createThreadStreamEntry,
		nextThreadEntryMap,
    patchThreadEntry,
    resolveThinkingModeForRequest,
  } = loadFunctions(
    "apps/web/src/features/thread-stream/stream-entry-state.ts",
    [
      "resolveThinkingModeForRequest",
      "createThreadStreamEntry",
      "nextThreadEntryMap",
      "patchThreadEntry",
    ],
  );
  const { resolveStreamRequestCleanup } = loadFunctions(
    "apps/web/src/features/thread-stream/use-thread-stream-errors.ts",
    ["resolveStreamRequestCleanup"],
  );

  assert.equal(
    JSON.stringify(resolveStreamRequestCleanup(false, false)),
    JSON.stringify({
      clearActiveThread: false,
      clearPendingUserMessage: true,
      clearStreamState: false,
    }),
  );
  assert.equal(
    JSON.stringify(resolveStreamRequestCleanup(false, true)),
    JSON.stringify({
      clearActiveThread: true,
      clearPendingUserMessage: true,
      clearStreamState: true,
    }),
  );
  assert.equal(
    resolveThinkingModeForRequest({ thinkingMode: "" }, "disabled"),
    "",
  );
  const threadAEntry = createThreadStreamEntry({
    isStreaming: true,
    pendingUserMessage: {
      id: "pending-a",
      content: "hello from a",
      threadId: "thread-a",
    },
  });
  const threadBEntry = createThreadStreamEntry({
    isStreaming: true,
    pendingUserMessage: {
      id: "pending-b",
      content: "hello from b",
      threadId: "thread-b",
    },
  });

  const withThreadA = nextThreadEntryMap({}, "thread-a", threadAEntry);
  const withBothThreads = nextThreadEntryMap(withThreadA, "thread-b", threadBEntry);
  const cleanedThreadA = patchThreadEntry(withBothThreads, "thread-a", {
    isStreaming: false,
    pendingUserMessage: null,
    streamState: null,
  });

  assert.equal(cleanedThreadA["thread-a"], undefined);
  assert.equal(cleanedThreadA["thread-b"].pendingUserMessage.content, "hello from b");
  assert.equal(cleanedThreadA["thread-b"].isStreaming, true);
});

test("stream reducer filters textual tool-call artifacts from visible text", () => {
  const {
    createInitialStreamState,
    looksLikeTextualToolCallArtifact,
    reduceStreamEvent,
    safeVisibleText,
  } = loadSdkStreamFunctions();
  const chineseToolDeliberation =
    '和 websearch。我因为不满意搜索结果而犹豫和重复调用，这是不对的。现在我直接执行：1. webfetch抓取 Threads帖子；2. web_search英文搜索 "OpenAI Codex latest news May2026"。';

  assert.equal(looksLikeTextualToolCallArtifact("[web_fetch] 尝试获取沪指数据，请稍等。"), true);
  assert.equal(looksLikeTextualToolCallArtifact(chineseToolDeliberation), true);
  assert.equal(
    looksLikeTextualToolCallArtifact(
      '让我进一步获取几个关键来源的详细内容，以便给出更有深度的回答。\n\n< | | DSML | | tool_calls>\n< | | DSML | | invoke nameweb_search">\n< | | DSML | | parameter name="query" string="true">AI breakthroughs</ | | DSML | | parameter>',
    ),
    true,
  );
  assert.equal(
    looksLikeTextualToolCallArtifact(
      'toolcalls/invoke namewebfetch">\nparameter namemax_chars" string="false">8000</ | | DSML | | parameter>\nparameter nameurl" string="true">https://example.com</ | | DSML | | parameter>',
    ),
    true,
  );
  assert.equal(
    looksLikeTextualToolCallArtifact(
      'invoke name">\nparameter name="" string="true">direct</ | | DSML | | parameter>\nparameter name="" string="true">https://mem0.ai/blog/state-of-ai-agent-memory-2026</ | | DSML | | parameter>',
    ),
    true,
  );
  assert.equal(
    looksLikeTextualToolCallArtifact(
      '· invoke name 2025 trends predictions multi-agent collaboration future</ | | DSML | | parameter>\nparameter name6</ | | DSML | | parameter>',
    ),
    true,
  );
  assert.equal(looksLikeTextualToolCallArtifact("invoke name"), true);
  assert.equal(looksLikeTextualToolCallArtifact("parameter name"), true);
  assert.equal(looksLikeTextualToolCallArtifact("| | DSML | |"), true);
  assert.equal(looksLikeTextualToolCallArtifact("</｜｜DSML｜｜parameter>"), true);
  assert.equal(
    looksLikeTextualToolCallArtifact(
      '<tool_c>\n<invoke="web_fetch">\n<parameterurl" string="true">https://vectorize.io/articles/best-ai-agent-memory-systems</parameter>\n<parametermax_chars" string="false">12000</parameter>\n</invoke>\n</tool_c>',
    ),
    true,
  );
  assert.equal(looksLikeTextualToolCallArtifact('alls>\n="web_search">'), true);
  assert.equal(looksLikeTextualToolCallArtifact('="query" string="true">AI agent predictions'), true);
  assert.equal(
    looksLikeTextualToolCallArtifact('="web_fetch="url" string="true">https://www.gartner.com/en/articles'),
    true,
  );
  assert.equal(looksLikeTextualToolCallArtifact('="max_chars" stringfalse">8000'), true);
  assert.equal(looksLikeTextualToolCallArtifact('="query"true">AI agent frameworks comparison'), true);
  assert.equal(
    looksLikeTextualToolCallArtifact(
      '="url"true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026',
    ),
    true,
  );
  assert.equal(looksLikeTextualToolCallArtifact('="max_chars"false">6000'), true);
  assert.equal(
    looksLikeTextualToolCallArtifact("https://www.shrutigupta01.com/ai-agent-frameworks-in-2026/parameter>"),
    true,
  );
  assert.equal(looksLikeTextualToolCallArtifact("12000parameter>"), true);
  assert.equal(looksLikeTextualToolCallArtifact("invoke>"), true);
  assert.equal(looksLikeTextualToolCallArtifact('="max_fetch_length" stringfalse8000parameter>'), true);
  assert.equal(
    looksLikeTextualToolCallArtifact(
      '="read="filepath" string="true">tool-observation://webfetch/2026/state-of-agents',
    ),
    true,
  );
  assert.equal(looksLikeTextualToolCallArtifact("tool-result://web_search/call-123"), true);
  assert.equal(looksLikeTextualToolCallArtifact("DSML 是一种标记格式说明。"), false);
  assert.equal(
    looksLikeTextualToolCallArtifact("让我尝试获取更详细的日线数据：我已经从搜索结果中获取到了关键信息。"),
    true,
  );
  assert.equal(
    looksLikeTextualToolCallArtifact(
      "我来帮你查询华钰矿业（601020）近一周的行情数据。先获取详细的历史交易数据。让我查询东方财富网的具体行情页面。如果没有新指示，我将默认继续执行。请确认是否继续。",
    ),
    true,
  );
  assert.equal(looksLikeTextualToolCallArtifact("</tool_call>"), true);
  assert.equal(
    looksLikeTextualToolCallArtifact(
      '<tool_req name="run_shell_command">\n<arg name="command" string="true">python3 scripts/stocks_client.py quote 601020.SS</arg>\n</tool_req>',
    ),
    true,
  );
  assert.equal(
    looksLikeTextualToolCallArtifact(
      '<toolreq name="runshell_command">\n<arg name="command" string="true">python3 scripts/stocks_client.py quote 601020.SS</arg>\n</toolreq>',
    ),
    true,
  );
  assert.equal(looksLikeTextualToolCallArtifact("function=web_search>"), true);
  assert.equal(looksLikeTextualToolCallArtifact("<parameter=query>比亚迪</parameter>"), true);
  assert.equal(looksLikeTextualToolCallArtifact("[背景] 沪指本周震荡。"), false);
  assert.equal(looksLikeTextualToolCallArtifact("我来帮你分析这份报告：结论是现金流改善。"), false);
  assert.equal(looksLikeTextualToolCallArtifact("普通文本里提到 invoke name resolution。"), false);
  assert.equal(safeVisibleText("</tool_call>"), "");
  assert.equal(
    safeVisibleText(
      '<tool_req name="run_shell_command">\n<arg name="command" string="true">python3 scripts/stocks_client.py quote 601020.SS</arg>\n</tool_req>',
    ),
    "",
  );
  assert.equal(
    safeVisibleText(
      '<toolreq name="runshell_command">\n<arg name="command" string="true">python3 scripts/stocks_client.py quote 601020.SS</arg>\n</toolreq>',
    ),
    "",
  );
  assert.equal(safeVisibleText('<arg name="timeout" string="false">30</arg>'), "");
  assert.equal(safeVisibleText("function=web_search>"), "");
  assert.equal(safeVisibleText("invoke name"), "");
  assert.equal(safeVisibleText("parameter name"), "");
  assert.equal(safeVisibleText("| | DSML | |"), "");
  assert.equal(safeVisibleText("</｜｜DSML｜｜parameter>"), "");
  assert.equal(safeVisibleText('<tool_c>\n<invoke="web_fetch">'), "");
  assert.equal(safeVisibleText('alls>\n="web_search">'), "");
  assert.equal(safeVisibleText('="query" string="true">AI agent predictions'), "");
  assert.equal(
    safeVisibleText('="web_fetch="url" string="true">https://www.gartner.com/en/articles'),
    "",
  );
  assert.equal(safeVisibleText('="max_chars" stringfalse">8000'), "");
  assert.equal(safeVisibleText('="query"true">AI agent frameworks comparison'), "");
  assert.equal(
    safeVisibleText('="url"true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026'),
    "",
  );
  assert.equal(safeVisibleText('="max_chars"false">6000'), "");
  assert.equal(safeVisibleText("https://www.shrutigupta01.com/ai-agent-frameworks-in-2026/parameter>"), "");
  assert.equal(safeVisibleText("12000parameter>"), "");
  assert.equal(safeVisibleText("invoke>"), "");
  assert.equal(safeVisibleText('="max_fetch_length" stringfalse8000parameter>'), "");
  assert.equal(
    safeVisibleText('="read="filepath" string="true">tool-observation://webfetch/2026/state-of-agents'),
    "",
  );
  assert.equal(
    safeVisibleText(
      'toolcalls/invoke namewebfetch">\nparameter namemax_chars" string="false">8000</ | | DSML | | parameter>',
    ),
    "",
  );
  assert.equal(safeVisibleText('toolcalls/invoke namewebfetch">'), "");
  assert.equal(
    safeVisibleText(
      'invoke name">\nparameter name="" string="true">direct</ | | DSML | | parameter>',
    ),
    "",
  );
  assert.equal(
    safeVisibleText(
      '· invoke name 2025 trends predictions multi-agent collaboration future</ | | DSML | | parameter>',
    ),
    "",
  );
  assert.equal(safeVisibleText("[web_search] searching"), "");
  assert.equal(safeVisibleText("**[web_fetch]** 尝试通过东方财富API获取数据。"), "");
  assert.equal(safeVisibleText(chineseToolDeliberation), "");
  assert.equal(safeVisibleText("让我尝试获取更详细的日线数据："), "");
  assert.equal(safeVisibleText("让我进一步获取几个关键来源的详细内容，以便给出更有深度的回答。"), "");
  assert.equal(safeVisibleText("如果没有新指示，我将默认继续执行。请确认是否继续。"), "");
  assert.equal(safeVisibleText("Let me fetch the latest sources first."), "");
  assert.equal(safeVisibleText("I should look for a few more references."), "");
  assert.equal(safeVisibleText("Wait, I need to call the search tool."), "");
  assert.equal(safeVisibleText("Final answer: tool call follows"), "");
  assert.equal(
    safeVisibleText("Let me produce the final answer. I must not call more tools. Let's go.最终答案。"),
    "最终答案。",
  );
  assert.equal(
    safeVisibleText('{"tool_calls":[{"name":"web_search","args":{"query":"x"}}]}'),
    "",
  );
  assert.equal(
    safeVisibleText('{"function_call":{"name":"web_fetch","arguments":"{\\"url\\":\\"https://x\\"}"}}'),
    "",
  );

  const withArtifactDelta = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "[web_fetch] 尝试获取沪指数据，请稍等。",
      channel: "message",
    },
  });
  assert.equal(withArtifactDelta.visibleText, "");

  const withChineseToolDeliberation = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: chineseToolDeliberation,
      channel: "message",
    },
  });
  assert.equal(withChineseToolDeliberation.visibleText, "");

  let withSplitChineseToolDeliberation = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "我因为",
      channel: "message",
    },
  });
  assert.equal(withSplitChineseToolDeliberation.visibleText, "");
  withSplitChineseToolDeliberation = reduceStreamEvent(withSplitChineseToolDeliberation, {
    event: "message.delta",
    data: {
      delta: "不满意搜索结果而犹豫和重复调用，这是不对的。现在我直接执行：",
      channel: "message",
    },
  });
  assert.equal(withSplitChineseToolDeliberation.visibleText, "");

  const withBareChineseToolFragment = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "和 websearch。",
      channel: "message",
    },
  });
  assert.equal(withBareChineseToolFragment.visibleText, "");

  let withSplitArtifact = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "function",
      channel: "message",
    },
  });
  assert.equal(withSplitArtifact.visibleText, "");
  withSplitArtifact = reduceStreamEvent(withSplitArtifact, {
    event: "message.delta",
    data: {
      delta:
        "=web_search>\n<parameter=query>比亚迪 002594 2026年4月 单日涨幅 最大</parameter>",
      channel: "message",
    },
  });
  assert.equal(withSplitArtifact.visibleText, "");

  let withSpacedDsmlArtifact = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "让我进一步获取几个关键来源的详细内容，以便给出更有深度的回答。",
      channel: "message",
    },
  });
  assert.equal(withSpacedDsmlArtifact.visibleText, "");
  withSpacedDsmlArtifact = reduceStreamEvent(withSpacedDsmlArtifact, {
    event: "message.delta",
    data: {
      delta:
        '\n\n< | | DSML | | tool_calls>\n< | | DSML | | invoke nameweb_search">\n< | | DSML | | parameter name="query" string="true">AI breakthroughs</ | | DSML | | parameter>',
      channel: "message",
    },
  });
  assert.equal(withSpacedDsmlArtifact.visibleText, "");

  let withCompactedDsmlArtifact = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "toolcalls/",
      channel: "message",
    },
  });
  assert.equal(withCompactedDsmlArtifact.visibleText, "");
  withCompactedDsmlArtifact = reduceStreamEvent(withCompactedDsmlArtifact, {
    event: "message.delta",
    data: {
      delta:
        'invoke namewebfetch">\nparameter namemax_chars" string="false">8000</ | | DSML | | parameter>',
      channel: "message",
    },
  });
  assert.equal(withCompactedDsmlArtifact.visibleText, "");

  let withDegradedInvokeName = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "invoke",
      channel: "message",
    },
  });
  assert.equal(withDegradedInvokeName.visibleText, "");
  withDegradedInvokeName = reduceStreamEvent(withDegradedInvokeName, {
    event: "message.delta",
    data: {
      delta:
        " name 2025 trends predictions multi-agent collaboration future</ | | DSML | | parameter>\nparameter name6",
      channel: "message",
    },
  });
  assert.equal(withDegradedInvokeName.visibleText, "");

  let withSplitBareDsml = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "< | | ",
      channel: "message",
    },
  });
  assert.equal(withSplitBareDsml.visibleText, "");
  withSplitBareDsml = reduceStreamEvent(withSplitBareDsml, {
    event: "message.delta",
    data: {
      delta: "DSML | | invoke nameweb_search",
      channel: "message",
    },
  });
  assert.equal(withSplitBareDsml.visibleText, "");

  let withSplitXmlishToolC = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "<tool",
      channel: "message",
    },
  });
  assert.equal(withSplitXmlishToolC.visibleText, "");
  withSplitXmlishToolC = reduceStreamEvent(withSplitXmlishToolC, {
    event: "message.delta",
    data: {
      delta: '_c>\n<invoke="web_fetch">',
      channel: "message",
    },
  });
  assert.equal(withSplitXmlishToolC.visibleText, "");

  let withSplitToolReq = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "<tool",
      channel: "message",
    },
  });
  assert.equal(withSplitToolReq.visibleText, "");
  withSplitToolReq = reduceStreamEvent(withSplitToolReq, {
    event: "message.delta",
    data: {
      delta:
        '_req name="run_shell_command">\n<arg name="command" string="true">python3 scripts/stocks_client.py quote 601020.SS</arg>\n</tool_req>',
      channel: "message",
    },
  });
  assert.equal(withSplitToolReq.visibleText, "");

  let withSplitToolReqArg = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "<arg",
      channel: "message",
    },
  });
  assert.equal(withSplitToolReqArg.visibleText, "");
  withSplitToolReqArg = reduceStreamEvent(withSplitToolReqArg, {
    event: "message.delta",
    data: {
      delta: ' name="command" string="true">python3 scripts/stocks_client.py quote 601020.SS</arg>',
      channel: "message",
    },
  });
  assert.equal(withSplitToolReqArg.visibleText, "");

  const withOrphanedToolTail = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta:
        'alls>\n="web_search">\n="query" string="true">AI agent predictions\n="query"true">AI agent frameworks comparison\n="web_fetch="url" string="true">https://www.gartner.com/en/articles\n="url"true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026\n="max_chars" stringfalse">8000\n="max_chars"false">6000',
      channel: "message",
    },
  });
  assert.equal(withOrphanedToolTail.visibleText, "");

  let withBareParameterName = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "parameter",
      channel: "message",
    },
  });
  assert.equal(withBareParameterName.visibleText, "");

  let withSplitObservationUri = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: '="read',
      channel: "message",
    },
  });
  assert.equal(withSplitObservationUri.visibleText, "");
  withSplitObservationUri = reduceStreamEvent(withSplitObservationUri, {
    event: "message.delta",
    data: {
      delta: '="filepath" string="true">tool-observation://webfetch/2026/state-of-agents',
      channel: "message",
    },
  });
  assert.equal(withSplitObservationUri.visibleText, "");

  let withCompactedParameterTail = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: '="url"',
      channel: "message",
    },
  });
  assert.equal(withCompactedParameterTail.visibleText, "");
  withCompactedParameterTail = reduceStreamEvent(withCompactedParameterTail, {
    event: "message.delta",
    data: {
      delta: 'true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026',
      channel: "message",
    },
  });
  assert.equal(withCompactedParameterTail.visibleText, "");
  withCompactedParameterTail = reduceStreamEvent(withCompactedParameterTail, {
    event: "message.delta",
    data: {
      delta: "</｜｜DSML｜｜parameter>",
      channel: "message",
    },
  });
  assert.equal(withCompactedParameterTail.visibleText, "");

  let withBareUrlParameterTail = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "https://www.shrutigupta01.com/ai-agent-frameworks-in-2026/",
      channel: "message",
    },
  });
  assert.equal(withBareUrlParameterTail.visibleText, "");
  withBareUrlParameterTail = reduceStreamEvent(withBareUrlParameterTail, {
    event: "message.delta",
    data: {
      delta: "parameter>",
      channel: "message",
    },
  });
  assert.equal(withBareUrlParameterTail.visibleText, "");

  let withNormalUrl = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "https://example.com/article",
      channel: "message",
    },
  });
  assert.equal(withNormalUrl.visibleText, "");
  withNormalUrl = reduceStreamEvent(withNormalUrl, {
    event: "message.delta",
    data: {
      delta: " is a normal cited URL.",
      channel: "message",
    },
  });
  assert.equal(withNormalUrl.visibleText, "https://example.com/article is a normal cited URL.");

  withBareParameterName = reduceStreamEvent(withBareParameterName, {
    event: "message.delta",
    data: {
      delta: " name",
      channel: "message",
    },
  });
  assert.equal(withBareParameterName.visibleText, "");

  let withNaturalFunctionText = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "function",
      channel: "message",
    },
  });
  withNaturalFunctionText = reduceStreamEvent(withNaturalFunctionText, {
    event: "message.delta",
    data: {
      delta: " 是 JavaScript 中声明函数的关键字。",
      channel: "message",
    },
  });
  assert.equal(withNaturalFunctionText.visibleText, "function 是 JavaScript 中声明函数的关键字。");

  const withPlainDelta = reduceStreamEvent(withArtifactDelta, {
    event: "message.delta",
    data: {
      delta: "沪指本周震荡回稳。",
      channel: "message",
    },
  });
  assert.equal(withPlainDelta.visibleText, "沪指本周震荡回稳。");

  const withInternalProcessDelta = reduceStreamEvent(withPlainDelta, {
    event: "message.delta",
    data: {
      delta: "我来帮你查询华钰矿业（601020）近一周的行情数据。请确认是否继续。",
      channel: "message",
    },
  });
  assert.equal(withInternalProcessDelta.visibleText, "沪指本周震荡回稳。");

  const withEnglishProcessDelta = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "Let me fetch more sources first.",
      channel: "message",
    },
  });
  assert.equal(withEnglishProcessDelta.visibleText, "");

  const withMixedFinalDelta = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "Let me produce the final answer. I must not call more tools. Let's go.最终答案。",
      channel: "message",
    },
  });
  assert.equal(withMixedFinalDelta.visibleText, "最终答案。");

  const withArtifactCompleted = reduceStreamEvent(withPlainDelta, {
    event: "message.completed",
    data: {
      content: "[web_fetch] 继续获取数据。",
    },
  });
  assert.equal(withArtifactCompleted.visibleText, "");

  let withReasoningArtifact = reduceStreamEvent(createInitialStreamState(), {
    event: "reasoning.delta",
    data: {
      delta: "tool",
    },
  });
  assert.equal(withReasoningArtifact.reasoningText, "");
  assert.equal(withReasoningArtifact.processingSteps.length, 0);
  withReasoningArtifact = reduceStreamEvent(withReasoningArtifact, {
    event: "reasoning.delta",
    data: {
      delta: 'calls/invoke namewebfetch">\nparameter name=""',
    },
  });
  assert.equal(withReasoningArtifact.reasoningText, "");
  assert.equal(withReasoningArtifact.processingSteps.length, 0);

  const withTaskArtifact = reduceStreamEvent(createInitialStreamState(), {
    event: "task.update",
    data: {
      id: "task-1",
      label: "Task",
      status: "running",
      value: 'invoke name">\nparameter name="" string="true">direct',
    },
  });
  assert.equal(withTaskArtifact.processingSteps.length, 1);
  assert.equal(withTaskArtifact.processingSteps[0].content, undefined);
});

test("stream reducer maintains processing steps alongside canonical run fields", () => {
  const { createInitialStreamState, reduceStreamEvent } = loadSdkStreamFunctions();

  let state = createInitialStreamState();
  assert.equal(Array.isArray(state.processingSteps), true);
  assert.equal(state.processingSteps.length, 0);
  assert.equal(state.activePhase, undefined);

  state = reduceStreamEvent(state, {
    event: "run.status",
    data: { thread_id: "thread-1", phase: "thinking" },
  });
  assert.equal(state.activePhase, "thinking");

  state = reduceStreamEvent(state, {
    event: "reasoning.delta",
    data: {
      thread_id: "thread-1",
      delta: "Looking",
      channel: "reasoning_tool_call",
    },
  });
  state = reduceStreamEvent(state, {
    event: "reasoning.delta",
    data: {
      thread_id: "thread-1",
      delta: " closer.",
      channel: "reasoning_tool_call",
    },
  });
  assert.equal(state.reasoningText, "Looking closer.");
  assert.equal(state.processingSteps.length, 1);
  assert.equal(state.processingSteps[0].kind, "reasoning");
  assert.equal(state.processingSteps[0].content, "Looking closer.");
  assert.equal(state.processingSteps[0].status, "running");

  state = reduceStreamEvent(state, {
    event: "reasoning.delta",
    data: {
      thread_id: "thread-1",
      delta: "",
      completed: true,
      content: "Done reasoning.",
    },
  });
  const reasoningStep = state.processingSteps.find((step) => step.kind === "reasoning");
  assert.equal(state.reasoningText, "Done reasoning.");
  assert.equal(reasoningStep.status, "completed");
  assert.equal(reasoningStep.content, "Done reasoning.");

  state = reduceStreamEvent(state, {
    event: "tool.call.delta",
    data: {
      thread_id: "thread-1",
      id: "call-1",
      name: "web_search",
      args_delta: '{"query"',
      channel: "reasoning_tool_call",
    },
  });
  state = reduceStreamEvent(state, {
    event: "tool.call.delta",
    data: {
      thread_id: "thread-1",
      id: "call-1",
      name: "web_search",
      args_delta: ':"focus"}',
      channel: "reasoning_tool_call",
    },
  });
  assert.equal(state.toolCalls.length, 2);
  let toolStep = state.processingSteps.find((step) => step.kind === "tool" && step.id === "call-1");
  assert.equal(toolStep.name, "web_search");
  assert.equal(toolStep.argsText, '{"query":"focus"}');
  assert.equal(toolStep.status, "running");

  state = reduceStreamEvent(state, {
    event: "tool.requested",
    data: {
      thread_id: "thread-1",
      tool_call_id: "call-1",
      tool_name: "web_search",
      args: { query: "focus" },
    },
  });
  state = reduceStreamEvent(state, {
    event: "tool.result",
    data: {
      thread_id: "thread-1",
      tool_call_id: "call-1",
      tool_name: "web_search",
      output: { title: "Focus Agent" },
    },
  });
  assert.equal(state.toolEvents.length, 2);
  toolStep = state.processingSteps.find((step) => step.kind === "tool" && step.id === "call-1");
  assert.equal(toolStep.status, "completed");
  assert.equal(toolStep.content, '{"title":"Focus Agent"}');
  assert.equal(toolStep.result.title, "Focus Agent");

  state = reduceStreamEvent(state, {
    event: "task.update",
    data: {
      thread_id: "thread-1",
      id: "task-1",
      event: "collect_sources",
      status: "running",
      value: "Collect sources",
    },
  });
  state = reduceStreamEvent(state, {
    event: "task.update",
    data: {
      thread_id: "thread-1",
      id: "task-1",
      event: "collect_sources",
      status: "completed",
      value: "Sources collected",
    },
  });
  const taskStep = state.processingSteps.find((step) => step.kind === "task" && step.id === "task-1");
  assert.equal(taskStep.label, "collect_sources");
  assert.equal(taskStep.status, "completed");
  assert.equal(taskStep.content, "Sources collected");

  state = reduceStreamEvent(state, {
    event: "run.completed",
    data: {
      thread_id: "thread-1",
      status: "succeeded",
      thread_state: { done: true },
    },
  });
  assert.equal(state.processingSteps.length, 3);
  assert.equal(state.latestTurnState.done, true);

  state = reduceStreamEvent(state, {
    event: "run.failed",
    data: {
      thread_id: "thread-1",
      error: "boom",
      message: "failed",
    },
  });
  const failedReasoningStep = state.processingSteps.find((step) => step.kind === "reasoning");
  assert.equal(state.activePhase, "failed");
  assert.equal(state.failed.error, "boom");
  assert.equal(state.isClosed, true);
  assert.equal(failedReasoningStep.status, "completed");
  assert.equal(toolStep.status, "completed");
});

test("SDK stream preserves canonical v2 events without legacy alias rewriting", async () => {
  const { canonicalizeStreamEvents } = loadModule("frontend-sdk/src/client/stream.ts");
  async function* rawEvents() {
    yield {
      event: "message.delta",
      data: { delta: "hello", channel: "message" },
    };
    yield {
      event: "message.delta",
      data: { delta: "hello", channel: "message" },
    };
    yield {
      event: "message.delta",
      data: { delta: " world", channel: "message" },
    };
    yield {
      event: "tool.call.delta",
      data: { id: "call-1", name: "search", args_delta: '{"q"', channel: "reasoning_tool_call" },
    };
  }

  const events = [];
  for await (const event of canonicalizeStreamEvents(rawEvents())) {
    events.push(event);
  }

  assert.deepEqual(
    events.map((event) => [event.event, event.data.delta ?? event.data.args_delta]),
    [
      ["message.delta", "hello"],
      ["message.delta", "hello"],
      ["message.delta", " world"],
      ["tool.call.delta", '{"q"'],
    ],
  );
});

test("SDK stream deduplicates replayed SSE ids while preserving unkeyed deltas", async () => {
  const { canonicalizeStreamEvents } = loadModule("frontend-sdk/src/client/stream.ts");
  async function* rawEvents() {
    yield {
      id: "event-1",
      event: "message.delta",
      data: { delta: "hello", channel: "message" },
    };
    yield {
      id: "event-1",
      event: "message.delta",
      data: { delta: "hello", channel: "message" },
    };
    yield {
      event: "message.delta",
      data: { delta: "!", channel: "message" },
    };
    yield {
      event: "message.delta",
      data: { delta: "!", channel: "message" },
    };
  }

  const events = [];
  for await (const event of canonicalizeStreamEvents(rawEvents())) {
    events.push(event);
  }

  assert.deepEqual(
    events.map((event) => [event.id ?? "", event.event, event.data.delta]),
    [
      ["event-1", "message.delta", "hello"],
      ["", "message.delta", "!"],
      ["", "message.delta", "!"],
    ],
  );
});

test("SDK streaming exposes only v2 harness endpoints for chat streams", () => {
	const streamingSource = readFileSync(
		path.join(repoRoot, "frontend-sdk/src/client/streaming.ts"),
		"utf8",
  );

  assert.equal(streamingSource.includes("return streamHarnessRun.call("), true);
  assert.equal(streamingSource.includes("async function streamHarnessRunEvents"), true);
  assert.equal(streamingSource.includes("/v2/runs/${encodeURIComponent(runId)}/stream"), true);
  assert.equal(
    streamingSource.includes("/v2/threads/${encodeURIComponent(request.thread_id)}/runs/resume/stream"),
    true,
  );
  assert.equal(streamingSource.includes("async function streamLegacyTurn"), false);
  assert.equal(streamingSource.includes("/v1/chat/turns/stream"), false);
	assert.equal(streamingSource.includes("async function streamLegacyResume"), false);
	assert.equal(streamingSource.includes("/v1/chat/resume/stream"), false);
});

test("SDK stream stops waiting after terminal v2 run events", () => {
	const clientSource = readFileSync(
		path.join(repoRoot, "frontend-sdk/src/client.ts"),
		"utf8",
	);
	const compactClientSource = compactSource(clientSource);

	assert.equal(clientSource.includes('import { isTerminalEvent } from "./guards.js";'), true);
	assert.equal(
		compactClientSource.includes(
			'if (event.event === "server_shutdown") { shouldReconnect = true; break; } if (isTerminalEvent(event)) { return; }',
		),
		true,
	);
});

test("stream reducer consumes v2 harness run events without visible_text dependencies", () => {
	const { createInitialStreamState, reduceStreamEvent } = loadSdkStreamFunctions();

  let state = reduceStreamEvent(createInitialStreamState(), {
    event: "run.status",
    data: {
      run_id: "run-1",
      thread_id: "thread-1",
      turn_id: "run-1",
      sequence: 1,
      source_node: "harness",
      phase: "running",
    },
  });
  state = reduceStreamEvent(state, {
    event: "message.delta",
    data: {
      run_id: "run-1",
      thread_id: "thread-1",
      turn_id: "run-1",
      sequence: 2,
      source_node: "agent",
      delta: "Canonical",
      message_id: "msg-1",
      channel: "message",
    },
  });
  state = reduceStreamEvent(state, {
    event: "message.delta",
    data: {
      run_id: "run-1",
      thread_id: "thread-1",
      turn_id: "run-1",
      sequence: 3,
      source_node: "agent",
      delta: " answer.",
      message_id: "msg-1",
      channel: "message",
    },
  });
  state = reduceStreamEvent(state, {
    event: "tool.requested",
    data: {
      run_id: "run-1",
      thread_id: "thread-1",
      tool_call_id: "call-1",
      tool_name: "web_search",
      args: { query: "focus" },
    },
  });
  state = reduceStreamEvent(state, {
    event: "tool.call.delta",
    data: {
      run_id: "run-1",
      thread_id: "thread-1",
      id: "call-1",
      tool_call_id: "call-1",
      name: "web_search",
      args_delta: '{"query":"focus"}',
      channel: "reasoning_tool_call",
    },
  });
  state = reduceStreamEvent(state, {
    event: "tool.result",
    data: {
      run_id: "run-1",
      thread_id: "thread-1",
      tool_call_id: "call-1",
      tool_name: "web_search",
      content: '{"ok":true}',
    },
  });
  state = reduceStreamEvent(state, {
    event: "run.closed",
    data: {
      run_id: "run-1",
      thread_id: "thread-1",
      turn_id: "run-1",
      sequence: 7,
      source_node: "harness",
      status: "closed",
    },
  });

  assert.equal(state.activePhase, "running");
  assert.equal(state.visibleText, "Canonical answer.");
  assert.equal(state.toolCalls.length, 1);
  assert.equal(state.toolEvents.length, 2);
  assert.equal(state.processingSteps.length, 1);
  assert.equal(state.processingSteps[0].id, "call-1");
  assert.equal(state.processingSteps[0].status, "completed");
  assert.equal(state.processingSteps[0].result, '{"ok":true}');
  assert.equal(state.isClosed, true);

  const interrupted = reduceStreamEvent(createInitialStreamState(), {
    event: "run.interrupt",
    data: {
      run_id: "run-1",
      thread_id: "thread-1",
      turn_id: "run-1",
      sequence: 4,
      source_node: "harness",
      action: "interrupt",
    },
  });
  assert.equal(interrupted.activePhase, "interrupt");
});

test("stream reducer keeps visible text empty until message content follows tool-first events", () => {
  const { createInitialStreamState, reduceStreamEvent } = loadSdkStreamFunctions();

  const toolFirstEvents = [
    {
      event: "tool.requested",
      data: {
        run_id: "run-tool-first",
        thread_id: "thread-1",
        turn_id: "run-tool-first",
        sequence: 1,
        source_node: "agent",
        tool_call_id: "call-first",
        tool_name: "web_search",
        args: { query: "focus" },
      },
    },
    {
      event: "tool.result",
      data: {
        run_id: "run-tool-first",
        thread_id: "thread-1",
        turn_id: "run-tool-first",
        sequence: 2,
        source_node: "agent",
        tool_call_id: "call-first",
        tool_name: "web_search",
        output: { title: "Focus Agent" },
      },
    },
  ];

  const reduceToolFirstEvents = () =>
    toolFirstEvents.reduce(
      (state, event) => reduceStreamEvent(state, event),
      createInitialStreamState(),
    );

  const toolOnlyState = reduceToolFirstEvents();
  assert.equal(toolOnlyState.visibleText, "");
  assert.equal(
    JSON.stringify(toolOnlyState.toolEvents.map((event) => event.event)),
    JSON.stringify(["tool.requested", "tool.result"]),
  );
  assert.equal(toolOnlyState.toolEvents[0].data.tool_name, "web_search");
  assert.equal(toolOnlyState.toolEvents[0].data.tool_call_id, "call-first");
  assert.equal(toolOnlyState.processingSteps.length, 1);
  assert.equal(toolOnlyState.processingSteps[0].id, "call-first");
  assert.equal(toolOnlyState.processingSteps[0].kind, "tool");
  assert.equal(toolOnlyState.processingSteps[0].status, "completed");
  assert.equal(toolOnlyState.processingSteps[0].result.title, "Focus Agent");

  const withFinalDelta = reduceStreamEvent(toolOnlyState, {
    event: "message.delta",
    data: {
      run_id: "run-tool-first",
      thread_id: "thread-1",
      turn_id: "run-tool-first",
      sequence: 3,
      source_node: "agent",
      delta: "Answer after tools.",
      message_id: "msg-1",
      channel: "message",
    },
  });
  assert.equal(withFinalDelta.visibleText, "Answer after tools.");
  assert.equal(withFinalDelta.toolEvents.length, 2);
  assert.equal(withFinalDelta.processingSteps[0].status, "completed");

  const withFinalCompleted = reduceStreamEvent(reduceToolFirstEvents(), {
    event: "message.completed",
    data: {
      run_id: "run-tool-first",
      thread_id: "thread-1",
      turn_id: "run-tool-first",
      sequence: 3,
      source_node: "agent",
      content: "Completed answer after tools.",
      message_id: "msg-2",
      source: "agent",
    },
  });
  assert.equal(withFinalCompleted.visibleText, "Completed answer after tools.");
  assert.equal(withFinalCompleted.toolEvents.length, 2);
  assert.equal(withFinalCompleted.processingSteps[0].status, "completed");
});

test("stream reducer merges tool lifecycle events by namespace and name fallback", () => {
  const { createInitialStreamState, reduceStreamEvent } = loadSdkStreamFunctions();

  let state = reduceStreamEvent(createInitialStreamState(), {
    event: "tool.requested",
    data: {
      thread_id: "thread-1",
      namespace: ["planner", "tools"],
      tool_name: "search",
      args: { query: "focus" },
    },
  });
  state = reduceStreamEvent(state, {
    event: "tool.error",
    data: {
      thread_id: "thread-1",
      namespace: ["planner", "tools"],
      tool_name: "search",
      message: "network failed",
    },
  });

  assert.equal(state.toolEvents.length, 2);
  assert.equal(state.processingSteps.length, 1);
  assert.equal(state.processingSteps[0].id, "planner/tools:search");
  assert.equal(state.processingSteps[0].kind, "tool");
  assert.equal(state.processingSteps[0].name, "search");
  assert.equal(state.processingSteps[0].status, "failed");
  assert.equal(state.processingSteps[0].content, "network failed");
});

test("tool approval helpers preserve resume decision compatibility", () => {
  const { createToolApprovalDecision, isToolApprovalInterrupt } = loadFunctions(
    "frontend-sdk/src/guards.ts",
    ["createToolApprovalDecision", "isToolApprovalInterrupt"],
  );
  const interrupt = {
    kind: "tool_approval",
    interrupt_id: "tool-approval:call-approval:abc123",
    tool_name: "write_file",
    tool_call_id: "call-approval",
    redacted_args: { path: "README.md", api_token: "[REDACTED]" },
    risk_level: "high",
    policy_version: "tool_approval.v2",
    created_at: "2026-05-06T00:00:00+00:00",
  };

  assert.equal(
    JSON.stringify(createToolApprovalDecision(interrupt, true)),
    JSON.stringify({
      kind: "tool_approval",
      interrupt_id: "tool-approval:call-approval:abc123",
      tool_call_id: "call-approval",
      approved: true,
      reason: null,
    }),
  );
  assert.equal(isToolApprovalInterrupt(interrupt), true);
  assert.equal(isToolApprovalInterrupt({ ...interrupt, args: { path: "README.md" } }), false);
  assert.equal(isToolApprovalInterrupt({ ...interrupt, redacted_args: [] }), false);
});

test("web thread UI wires tool approval rendering to stream resume decisions", () => {
  const messageListSource = readFileSync(
    path.join(repoRoot, "apps/web/src/entities/messages/message-list.tsx"),
    "utf8",
  );
  const approvalCardSource = readFileSync(
    path.join(repoRoot, "apps/web/src/entities/messages/message-list-tool-approval-card.tsx"),
    "utf8",
  );
  const threadPageSource = readFileSync(
    path.join(repoRoot, "apps/web/src/pages/thread/thread-page.tsx"),
    "utf8",
  );
  const streamHookSource = readFileSync(
    path.join(repoRoot, "apps/web/src/features/thread-stream/use-thread-stream.ts"),
    "utf8",
  );
  const streamRegistrySource = readFileSync(
    path.join(repoRoot, "apps/web/src/features/thread-stream/use-stream-request-registry.ts"),
    "utf8",
  );
  const streamCacheSource = readFileSync(
    path.join(repoRoot, "apps/web/src/features/thread-stream/use-thread-stream-cache.ts"),
    "utf8",
  );

  assert.equal(messageListSource.includes("toolApprovalInterrupts.map"), true);
  assert.equal(approvalCardSource.includes("onDecide?.(interrupt, true)"), true);
  assert.equal(approvalCardSource.includes("onDecide?.(interrupt, false)"), true);
  assert.equal(approvalCardSource.includes("interrupt.redacted_args"), true);
  assert.equal(approvalCardSource.includes("interrupt.args"), false);
  assert.equal(threadPageSource.includes("handleDecideToolApproval"), true);
  assert.equal(streamHookSource.includes("client.streamResume"), true);
  assert.equal(
    compactSource(streamHookSource).includes("createToolApprovalDecision(interrupt, approved)"),
    true,
  );
  assert.equal(streamHookSource.includes("activeRunIdsRef"), true);
  assert.equal(
    compactSource(streamHookSource).includes("activeRunIdsRef.current.delete(requestThreadId);"),
    true,
  );
  assert.equal(
    compactSource(streamHookSource).includes(
      "const activeRunId = activeRunIdsRef.current.get(options.threadId); if (activeRunId)",
    ),
    true,
  );
  assert.equal(
    compactSource(streamHookSource).includes(
      'client .cancelHarnessRun(activeRunId, { action: "interrupt" })',
    ),
    true,
  );
  assert.equal(
    compactSource(streamHookSource).includes(
      'client .cancelThreadHarnessRuns(options.threadId, { action: "interrupt" })',
    ),
    true,
  );
  assert.equal(
    compactSource(streamRegistrySource).includes(
      "abortControllersRef.current.delete(threadId); activeRequestIdsRef.current.delete(threadId);",
    ),
    true,
  );
  assert.equal(streamHookSource.includes("resolveStreamRequestCleanup(false, true)"), true);
  assert.equal(
    compactSource(streamHookSource).includes(
      "sendSucceeded = nextState.isClosed && !nextState.failed && !controller.signal.aborted;",
    ),
    true,
  );
  assert.equal(
    compactSource(streamHookSource).includes(
      "requestRegistry.stopStreamRequest(options.threadId); activeRunIdsRef.current.delete(options.threadId);",
    ),
    true,
  );
  assert.equal(
    compactSource(streamHookSource).includes(
      "isStreaming: false, pendingUserMessage: cleanup.clearPendingUserMessage",
    ),
    true,
  );
  assert.equal(streamCacheSource.includes("isCompleteThreadState"), true);
  assert.equal(streamCacheSource.includes("Array.isArray(record.messages)"), true);
  assert.equal(streamCacheSource.includes("Array.isArray(record.branch_actions)"), true);
  assert.equal(
    compactSource(streamCacheSource).includes(
      "void queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) }); return;",
    ),
    true,
  );
  assert.equal(
    compactSource(streamCacheSource).includes(
      "if (threadState.thread_id !== threadId) { void queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadState.thread_id), }); void queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) }); return; }",
    ),
    true,
  );
});

test("SSE parser ignores trailing blank frames after stream completion", () => {
  const { parseSSEFrames } = loadModule("frontend-sdk/src/parser.ts");

  const parsed = parseSSEFrames(
    'event: message.completed\r\ndata: {"content":"done"}\r\n\r\n\r\n\r\n',
  );

  assert.equal(parsed.frames.length, 1);
  assert.equal(parsed.frames[0].event, "message.completed");
  assert.equal(parsed.frames[0].data, '{"content":"done"}');
  assert.equal(parseSSEFrames("\n\n").frames.length, 0);
});

test("SSE decode errors include raw frame context", () => {
  const { decodeEvent, FocusAgentSSEDecodeError } = loadModule("frontend-sdk/src/parser.ts");
  const frame = {
    event: "message.delta",
    data: '{"delta":',
    raw: 'event: message.delta\ndata: {"delta":',
  };

  assert.throws(
    () => decodeEvent(frame),
    (error) =>
      error instanceof FocusAgentSSEDecodeError &&
      error.frame.raw === frame.raw &&
      error.frame.event === "message.delta",
  );
});

test("SSE iterator cancels the reader when the consumer exits early", async () => {
  const { iterSSEEvents } = loadModule("frontend-sdk/src/parser.ts");
  let canceled = false;
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(
        new TextEncoder().encode('event: message.delta\ndata: {"delta":"hello"}\n\n'),
      );
    },
    cancel() {
      canceled = true;
    },
  });
  const iterator = iterSSEEvents(stream);

  const first = await iterator.next();
  assert.equal(first.done, false);
  assert.equal(first.value.event, "message.delta");
  await iterator.return();
  assert.equal(canceled, true);
});

test("message list does not render trailing tool output as a fake assistant reply", () => {
  const sourceText = readFileSync(
    path.join(repoRoot, "apps/web/src/entities/messages/message-transcript-builder.ts"),
    "utf8",
  );

  assert.equal(sourceText.includes("assistant-message-fallback"), true);
  assert.equal(sourceText.includes("lastItem.id}-summary"), false);
});

test("message transcript fallback does not duplicate a visible assistant reply", () => {
  const { buildTranscriptItems } = loadMessageTranscriptFunctions();

  const items = buildTranscriptItems(
    [
      { id: "user-1", type: "human", content: "Analyze this." },
      { id: "assistant-1", type: "ai", content: "Persisted answer." },
    ],
    "Different assistant_message fallback.",
  );

  const assistantItems = items.filter((item) => item.kind === "message" && item.type === "ai");
  assert.equal(assistantItems.length, 1);
  assert.equal(assistantItems[0].content, "Persisted answer.");
});

test("message transcript normalizes chat role aliases before fallback checks", () => {
  const { buildTranscriptItems } = loadMessageTranscriptFunctions();

  const items = buildTranscriptItems(
    [
      { id: "user-1", type: "user", content: "Analyze this." },
      { id: "assistant-1", type: "assistant", content: "Persisted answer." },
    ],
    "Different assistant_message fallback.",
  );

  const messageItems = items.filter((item) => item.kind === "message");
  assert.equal(
    JSON.stringify(messageItems.map((item) => [item.type, item.content])),
    JSON.stringify([
      ["human", "Analyze this."],
      ["ai", "Persisted answer."],
    ]),
  );
});

test("message transcript fallback remains available before assistant persistence", () => {
	const { buildTranscriptItems } = loadMessageTranscriptFunctions();

	const items = buildTranscriptItems(
		[{ id: "user-1", type: "human", content: "Analyze this." }],
		"Streaming answer.",
	);

  const assistantItems = items.filter((item) => item.kind === "message" && item.type === "ai");
	assert.equal(assistantItems.length, 1);
	assert.equal(assistantItems[0].content, "Streaming answer.");
});

test("message transcript reads OpenAI token usage aliases", () => {
	const { buildTranscriptItems, totalTokensFromUsageMetadata } = loadMessageTranscriptFunctions();

	assert.equal(
		totalTokensFromUsageMetadata({ prompt_tokens: 12, completion_tokens: 8 }),
		20,
	);

	const items = buildTranscriptItems([
		{ id: "user-1", type: "human", content: "Analyze this." },
		{
			id: "assistant-1",
			type: "ai",
			content: "Done.",
			usage_metadata: { prompt_tokens: 12, completion_tokens: 8 },
		},
	]);
	const assistantItems = items.filter((item) => item.kind === "message" && item.type === "ai");
	assert.equal(assistantItems[0].totalTokens, 20);
});

test("message transcript hides degraded tool protocol content from state and fallback", () => {
  const { buildTranscriptItems } = loadMessageTranscriptFunctions();

  const protocolTexts = [
    "invoke name\nparameter name\n| | DSML | |",
    '<tool_c>\n<invoke="web_fetch">\n<parameterurl" string="true">https://vectorize.io/articles/best-ai-agent-memory-systems</parameter>\n</invoke>\n</tool_c>',
    'alls>\n="web_search">\n="query" string="true">AI agent predictions',
    '="web_fetch="url" string="true">https://www.gartner.com/en/articles\n="max_chars" stringfalse">8000',
    '="url"true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026\n="max_chars"false">6000',
    "https://www.shrutigupta01.com/ai-agent-frameworks-in-2026/parameter>\n12000parameter>\ninvoke>",
    '="max_fetch_length" stringfalse8000parameter>',
    '="read="filepath" string="true">tool-observation://webfetch/2026/state-of-agents',
    '和 websearch。我因为不满意搜索结果而犹豫和重复调用，这是不对的。现在我直接执行：1. webfetch抓取 Threads帖子；2. web_search英文搜索 "OpenAI Codex latest news May2026"。',
  ];

  for (const protocolText of protocolTexts) {
    const stateItems = buildTranscriptItems([
      { id: "user-1", type: "human", content: "Search this." },
      { id: "assistant-protocol", type: "ai", content: protocolText },
    ]);
    const fallbackItems = buildTranscriptItems(
      [{ id: "user-1", type: "human", content: "Search this." }],
      protocolText,
    );

    assert.equal(
      stateItems.some((item) => item.kind === "message" && item.type === "ai"),
      false,
    );
    assert.equal(
      fallbackItems.some((item) => item.kind === "message" && item.type === "ai"),
      false,
    );
  }
});

test("message transcript shows only the latest visible assistant answer per turn", () => {
	const { buildTranscriptItems } = loadMessageTranscriptFunctions();

	const items = buildTranscriptItems(
		[
			{ id: "user-1", type: "human", content: "Analyze the market." },
			{
				id: "tool-call-1",
				type: "ai",
				content: "",
				tool_calls: [{ name: "web_search", args: { query: "market" } }],
			},
			{
				id: "tool-result-1",
				type: "tool",
				name: "web_search",
				content: '{"answer":"partial"}',
			},
			{ id: "assistant-draft", type: "ai", content: "First reflected draft." },
			{
				id: "tool-call-2",
				type: "ai",
				content: "",
				tool_calls: [{ name: "web_search", args: { query: "follow up" } }],
			},
			{
				id: "tool-result-2",
				type: "tool",
				name: "web_search",
				content: '{"answer":"final evidence"}',
			},
			{ id: "assistant-final", type: "ai", content: "Final answer." },
		],
		"Final answer.",
	);

	const assistantItems = items.filter((item) => item.kind === "message" && item.type === "ai");
	const toolItems = items.filter((item) => item.kind === "tool-activity");
	assert.equal(assistantItems.length, 1);
	assert.equal(assistantItems[0].content, "Final answer.");
	assert.equal(toolItems.length, 1);
	assert.equal(toolItems[0].steps.length, 2);
});

test("message transcript merges staged tool calls into one run activity and infers selected skills", () => {
	const { buildTranscriptItems } = loadMessageTranscriptFunctions();

	const items = buildTranscriptItems([
		{ id: "user-1", type: "human", content: "Use the stock skill." },
		{
			id: "assistant-tools-1",
			type: "ai",
			content: "",
			tool_calls: [{ id: "call-skills", name: "skills_search", args: { query: "stocks" } }],
		},
		{
			id: "tool-result-skills",
			type: "tool",
			tool_call_id: "call-skills",
			content: JSON.stringify({ results: [{ skill_id: "stocks" }] }),
		},
		{
			id: "assistant-tools-2",
			type: "ai",
			content: "",
			tool_calls: [
				{
					id: "call-command",
					name: "run_workspace_command",
					args: {
						cwd: "/tmp/work/.focus_agent/skills/stocks",
						command: ["python", "analyze.py"],
					},
				},
				{ id: "call-search", name: "web_search", args: { query: "market close" } },
			],
		},
		{
			id: "tool-result-command",
			type: "tool",
			tool_call_id: "call-command",
			name: "run_workspace_command",
			content: JSON.stringify({ output: "analysis ready" }),
		},
		{
			id: "tool-result-search",
			type: "tool",
			tool_call_id: "call-search",
			name: "web_search",
			content: JSON.stringify({ answer: "market data" }),
		},
		{ id: "assistant-final", type: "ai", content: "Final answer." },
	]);

	const toolItems = items.filter((item) => item.kind === "tool-activity");
	const assistantItems = items.filter((item) => item.kind === "message" && item.type === "ai");
	assert.equal(toolItems.length, 1);
	assert.equal(JSON.stringify(toolItems[0].skillIds), JSON.stringify(["stocks"]));
	assert.equal(
		JSON.stringify(toolItems[0].toolNames),
		JSON.stringify(["skills_search", "run_workspace_command", "web_search"]),
	);
	assert.equal(toolItems[0].steps.length, 3);
	assert.equal(assistantItems[0].content, "Final answer.");
});

test("message transcript infers skills from detail JSON metadata", () => {
	const { buildTranscriptItems } = loadMessageTranscriptFunctions();

	const items = buildTranscriptItems([
		{ id: "user-1", type: "human", content: "Show the selected skill." },
		{
			id: "assistant-tools-1",
			type: "ai",
			content: "",
			tool_calls: [{ id: "call-view", name: "skill_view", args: { skill_id: "stocks" } }],
		},
		{
			id: "tool-result-view",
			type: "tool",
			tool_call_id: "call-view",
			name: "skill_view",
			content: JSON.stringify({
				skill_id: "stocks",
				recommended_tools: ["run_workspace_command", "web_search"],
			}),
		},
	]);

	const toolItems = items.filter((item) => item.kind === "tool-activity");
	assert.equal(toolItems.length, 1);
	assert.equal(JSON.stringify(toolItems[0].skillIds), JSON.stringify(["stocks"]));
});

test("message transcript reads selected skills from backend turn metadata", () => {
	const { buildTranscriptItems } = loadMessageTranscriptFunctions();

	const items = buildTranscriptItems([
		{
			id: "user-1",
			type: "human",
			content: "Use the stock skill.",
			metadata: {
				active_skill_ids: ["stocks"],
				active_skills: [{ skill_id: "stocks", name: "Stocks" }],
			},
		},
		{
			id: "assistant-tools-1",
			type: "ai",
			content: "",
			metadata: {
				active_skills: [{ skill_id: "stocks", name: "Stocks" }],
			},
			tool_calls: [{ id: "call-search", name: "web_search", args: { query: "market close" } }],
		},
		{
			id: "tool-result-search",
			type: "tool",
			tool_call_id: "call-search",
			name: "web_search",
			content: JSON.stringify({ answer: "market data" }),
		},
	]);

	const toolItems = items.filter((item) => item.kind === "tool-activity");
	assert.equal(toolItems.length, 1);
	assert.equal(JSON.stringify(toolItems[0].skillIds), JSON.stringify(["stocks"]));
});

test("message transcript renders skill execution contract metadata in one activity", () => {
	const { buildTranscriptItems } = loadMessageTranscriptFunctions();

	const items = buildTranscriptItems([
		{ id: "user-1", type: "human", content: "华钰矿业近一周表现" },
		{
			id: "assistant-repair-1",
			type: "ai",
			content: "",
			turn_metadata: {
				selected_skill_ids: ["stocks"],
				skill_execution_plan: {
					selected_skill_ids: ["stocks"],
					primary_tools: ["run_workspace_command"],
					supporting_tools: ["web_search", "read_file"],
					runtime_cwds: { stocks: ".focus_agent/skills/stocks" },
				},
				execution_contract: {
					policy: "skill_execution",
					selected_skill_ids: ["stocks"],
					required_tools: ["run_workspace_command"],
					missing: ["run_workspace_command"],
					status: "missing_required_tools",
				},
				answer_verification: {
					status: "unsupported",
					repair_action_taken: "retry_skill_primary_tool",
				},
			},
			tool_calls: [
				{
					id: "call-stocks",
					name: "run_workspace_command",
					args: {
						command: ["python3", "scripts/stock_client.py", "quote"],
						cwd: ".focus_agent/skills/stocks",
					},
				},
			],
		},
	]);

	const toolItems = items.filter((item) => item.kind === "tool-activity");
	assert.equal(toolItems.length, 1);
	assert.equal(JSON.stringify(toolItems[0].skillIds), JSON.stringify(["stocks"]));
	assert.equal(
		JSON.stringify(toolItems[0].toolNames),
		JSON.stringify(["run_workspace_command"]),
	);
	const labels = toolItems[0].steps.map((step) => step.label);
	assert.equal(labels.includes("Skill plan"), true);
	assert.equal(labels.includes("Required tools"), true);
	assert.equal(labels.includes("Repair"), true);
	assert.equal(
		toolItems[0].steps.some((step) =>
			String(step.content || "").includes(".focus_agent/skills/stocks")
		),
		true,
	);
});

test("message transcript keeps historical tool results inside one tool activity", () => {
	const { buildTranscriptItems } = loadMessageTranscriptFunctions();
  const largeToolResult = JSON.stringify({
    answer: "tool-result-unique-large-payload",
    rows: Array.from({ length: 40 }, (_, index) => ({
      id: `row-${index}`,
      value: "x".repeat(80),
    })),
  });
  const failedToolResult = JSON.stringify({
    message: "lookup failed with timeout",
    retryable: true,
  });

  const items = buildTranscriptItems([
    { id: "user-1", type: "human", content: "Gather evidence." },
    {
      id: "assistant-tools-1",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "call-search",
          function: {
            name: "web_search",
            arguments: JSON.stringify({ query: "focus-agent regression" }),
          },
        },
        {
          id: "call-fetch",
          name: "web_fetch",
          args: { url: "https://example.test/large-result" },
        },
      ],
    },
    {
      id: "tool-result-search",
      type: "tool",
      tool_call_id: "call-search",
      name: "web_search",
      content: largeToolResult,
    },
    {
      id: "tool-result-fetch",
      type: "tool",
      tool_call_id: "call-fetch",
      name: "web_fetch",
      status: "error",
      content: failedToolResult,
    },
  ]);

  const assistantItems = items.filter((item) => item.kind === "message" && item.type === "ai");
  const toolItems = items.filter((item) => item.kind === "tool-activity");

  assert.equal(assistantItems.length, 0);
  assert.equal(toolItems.length, 1);
  assert.equal(
    JSON.stringify(toolItems[0].toolNames),
    JSON.stringify(["web_search", "web_fetch"]),
  );
  assert.equal(toolItems[0].details.length, 2);
  assert.equal(toolItems[0].details[0].label, "web_search");
  assert.equal(toolItems[0].details[0].language, "json");
  assert.match(toolItems[0].details[0].content, /tool-result-unique-large-payload/);
  assert.equal(toolItems[0].details[1].label, "web_fetch");
  assert.equal(toolItems[0].details[1].language, "json");

  assert.equal(toolItems[0].steps.length, 2);
  assert.equal(toolItems[0].steps[0].id, "call-search");
  assert.equal(toolItems[0].steps[0].status, "completed");
  assert.equal(toolItems[0].steps[0].detail.id, toolItems[0].details[0].id);
  assert.equal(toolItems[0].steps[1].id, "call-fetch");
  assert.equal(toolItems[0].steps[1].status, "failed");
  assert.equal(toolItems[0].steps[1].tone, "danger");
  assert.equal(toolItems[0].steps[1].detail.id, toolItems[0].details[1].id);
  assert.equal(
    items.some(
      (item) =>
        item.kind === "message" &&
        String(item.content).includes("tool-result-unique-large-payload"),
    ),
    false,
  );
});

test("trajectory previews hide internal tool and reasoning artifacts", () => {
	const { compactSnippet, extractStructuredSummary } =
		loadTrajectoryUtilityFunctions();

	assert.equal(
		compactSnippet('<｜DSML｜invoke name="web_fetch">hidden</｜DSML｜invoke>'),
		"",
	);
	assert.equal(
		extractStructuredSummary(
			'{"reasoning_content":"internal thinking","content":"final answer"}',
		),
		"",
	);
	assert.equal(compactSnippet("Final user-visible answer.", 120), "Final user-visible answer.");
});

test("thinking-capable model selection preserves unset backend-default semantics until the user toggles it", () => {
	const {
	effectiveThinkingModeForModel,
	nextThinkingModeForModelSelection,
	thinkingOptionMetaLabel,
    thinkingModeRequestValueForModel,
  } = loadFunctions("apps/web/src/features/thread-stream/message-composer-helpers.ts", [
    "normalizeThinkingMode",
    "thinkingAvailableLabel",
    "thinkingUnavailableLabel",
    "thinkingOnStatusLabel",
    "thinkingOffStatusLabel",
    "thinkingStatusText",
    "thinkingOptionMetaLabel",
    "effectiveThinkingModeForModel",
    "nextThinkingModeForModelSelection",
    "thinkingModeRequestValueForModel",
  ]);

  const model = { supports_thinking: true };

  assert.equal(effectiveThinkingModeForModel(model, ""), "");
  assert.equal(nextThinkingModeForModelSelection(model, "next-model", "current-model", "enabled"), "");
  assert.equal(thinkingOptionMetaLabel(model, "", false), "Thinking available, toggle manually");
  assert.equal(thinkingModeRequestValueForModel(model, ""), "");
  assert.equal(thinkingModeRequestValueForModel(model, "disabled"), "disabled");
});

test("model provider labels prefer backend catalog metadata over frontend guesses", () => {
  const { providerLogoLetter, providerLogoSlug, providerOptionLabel } = loadFunctions(
    "apps/web/src/features/thread-stream/message-composer-helpers.ts",
    ["providerLogoLetter", "providerLogoSlug", "providerOptionLabel"],
  );

  assert.equal(providerOptionLabel("mimo", false, "Xiaomi MiMo"), "Xiaomi MiMo");
  assert.equal(providerOptionLabel("mimo", true, "Xiaomi MiMo"), "Xiaomi MiMo");
  assert.equal(providerOptionLabel("unlisted", true, ""), "OpenAI 兼容");
  assert.equal(providerLogoSlug("moonshotai"), "moonshotai");
  assert.equal(providerLogoSlug(""), "");
  assert.equal(providerLogoLetter("mimo", "X"), "X");
  assert.equal(providerLogoLetter("mimo"), "M");
});

test("context meter formats current context usage separately from token spend", () => {
  const {
    contextUsagePercent,
    contextUsageRemainingPercent,
    contextUsageTone,
    formatContextMarkerCount,
    shouldShowContextCompactAction,
  } = loadFunctions("apps/web/src/features/thread-stream/message-composer-helpers.ts", [
    "formatContextMarkerCount",
    "contextUsagePercent",
    "contextUsageRemainingPercent",
    "shouldShowContextCompactAction",
    "contextUsageTone",
  ]);

  const usage = {
    used_tokens: 104000,
    token_limit: 258000,
    remaining_tokens: 154000,
    used_ratio: 0.4,
    status: "ok",
  };

  assert.equal(formatContextMarkerCount(104000), "104k");
  assert.equal(formatContextMarkerCount(258000), "258k");
  assert.equal(contextUsagePercent(usage), 40);
  assert.equal(contextUsageRemainingPercent(usage), 60);
  assert.equal(shouldShowContextCompactAction({ ...usage, used_ratio: 0.84, status: "warm" }), false);
  assert.equal(shouldShowContextCompactAction({ ...usage, used_ratio: 0.86, status: "hot" }), true);
  assert.equal(contextUsageTone({ ...usage, used_ratio: 0.72, status: "warm" }), "is-warm");
  assert.equal(contextUsageTone({ ...usage, used_ratio: 0.93, status: "over" }), "is-over");
});

test("markdown paragraph line keys avoid array index fallback for repeated tool markup lines", () => {
  const paragraphNode = loadMarkdownParagraphFunction();
  const paragraph = paragraphNode("same\nsame", "p-0");
  const fragments = paragraph.props.children[0];

  assert.equal(fragments.length, 2);
  assert.equal(fragments[0].key, "p-0-line-same-0");
  assert.equal(fragments[1].key, "p-0-line-same-1");
  assert.notEqual(fragments[0].key, fragments[1].key);
  assert.equal(fragments[0].props.children[0][0].key, "p-0-line-same-0-inline");
  assert.equal(fragments[1].props.children[0][0].key, "p-0-line-same-1-inline");
});

test("merge review navigates to the backend merge target thread", () => {
  const source = readFileSync(
    path.join(repoRoot, "apps/web/src/features/merge-review/merge-review-card.tsx"),
    "utf8",
  );
  const compact = compactSource(source);

  assert.match(compact, /const targetThreadId = response\\.target_thread_id \\|\\| threadId;/);
  assert.match(compact, /threadId: targetThreadId/);
});

test("composer action buttons are not nested inside the textarea label", () => {
  const source = readFileSync(
    path.join(repoRoot, "apps/web/src/features/thread-stream/message-composer.tsx"),
    "utf8",
  );
  const composerCss = readCssModule("apps/web/src/shared/styles/modules/composer.css");

  assert.equal(source.includes("const textareaId = useId();"), true);
  assert.match(source, /<label className="sr-only" htmlFor=\{textareaId\}>/);
  assert.match(source, /id=\{textareaId\}/);
  assert.doesNotMatch(
    source,
    /<label\s+className=\{`fa-composer-shell fa-composer-input-shell/,
  );
  assert.match(
    compactSource(composerCss),
    /\.fa-composer-icon, \.fa-composer-icon svg, \.fa-composer-icon \* \{ pointer-events: none; \}/,
  );
});

test("composer clears a submitted draft immediately and leaves it clear after stop", async () => {
  const { submitComposerMessage } = loadMessageComposerSubmitModule();
  let messageState = "Use stock SQL";
  let sentMessage = "";
  const updates = [];
  const setMessage = (value) => {
    messageState = typeof value === "function" ? value(messageState) : value;
    updates.push(messageState);
  };

  const submitPromise = submitComposerMessage({
    activeThinkingMode: "",
    editDraft: null,
    isReadOnly: false,
    isStreaming: false,
    message: messageState,
    modelId: "",
    onSendMessage: async (message) => {
      sentMessage = message;
      return { ok: false, aborted: true };
    },
    resetEditDraftSignature: () => undefined,
    setMessage,
  });

  assert.equal(sentMessage, "Use stock SQL");
  assert.equal(messageState, "");
  await submitPromise;
  assert.equal(messageState, "");
  assert.deepEqual(updates, [""]);
});

test("composer restores a submitted draft after non-aborted send failure only when empty", async () => {
  const { submitComposerMessage } = loadMessageComposerSubmitModule();
  let restoredState = "first draft";
  const setRestoredMessage = (value) => {
    restoredState =
      typeof value === "function" ? value(restoredState) : value;
  };

  await submitComposerMessage({
    activeThinkingMode: "",
    editDraft: null,
    isReadOnly: false,
    isStreaming: false,
    message: restoredState,
    modelId: "",
    onSendMessage: async () => ({ ok: false }),
    resetEditDraftSignature: () => undefined,
    setMessage: setRestoredMessage,
  });
  assert.equal(restoredState, "first draft");

  let newDraftState = "old draft";
  const setNewDraftMessage = (value) => {
    newDraftState =
      typeof value === "function" ? value(newDraftState) : value;
  };
  await submitComposerMessage({
    activeThinkingMode: "",
    editDraft: null,
    isReadOnly: false,
    isStreaming: false,
    message: newDraftState,
    modelId: "",
    onSendMessage: async () => {
      setNewDraftMessage("new draft");
      return { ok: false };
    },
    resetEditDraftSignature: () => undefined,
    setMessage: setNewDraftMessage,
  });
  assert.equal(newDraftState, "new draft");
});

test("branch action confirmation starts an automatic carried handoff run", () => {
  const branchActionSource = readFileSync(
    path.join(repoRoot, "apps/web/src/pages/thread/use-thread-branch-actions.ts"),
    "utf8",
  );
  const streamSource = readFileSync(
    path.join(repoRoot, "apps/web/src/features/thread-stream/use-thread-stream.ts"),
    "utf8",
  );
  const threadPageSource = readFileSync(
    path.join(repoRoot, "apps/web/src/pages/thread/thread-page.tsx"),
    "utf8",
  );
  const compactBranchAction = compactSource(branchActionSource);
  const compactStream = compactSource(streamSource);

  assert.equal(compactBranchAction.includes("result.branch_action.handoff_message"), true);
  assert.equal(compactBranchAction.includes("options.onRunHandoff?.("), true);
  assert.equal(
    compactBranchAction.includes(
      "const handoffRun = handoffMessage && navigation.thread_id !== sourceThreadId ? options.onRunHandoff?.(",
    ),
    true,
  );
  assert.equal(
    compactBranchAction.includes(
      "threadId: navigation.thread_id, message: handoffMessage, }) : undefined; await navigate",
    ),
    true,
  );
  assert.equal(threadPageSource.includes("composerSelectionOverridesRef"), true);
  assert.equal(threadPageSource.includes("if (!data?.selected_model && !data?.selected_thinking_mode)"), true);
  assert.match(threadPageSource, /runCarriedMessageInThread\(\s*targetThreadId,\s*message,\s*composerSelectionOverridesRef\.current,\s*\)/);
  assert.equal(threadPageSource.includes("onComposerSelectionChange={handleComposerSelectionChange}"), true);
  assert.equal(compactStream.includes("client.streamHarnessRun( requestThreadId,"), true);
  assert.equal(compactStream.includes("message: cleanMessage"), true);
  assert.equal(compactStream.includes("input: { messages: [] }"), false);
  assert.equal(compactStream.includes("branch_handoff_auto_run: true"), true);
});

test("thread busy retry helper waits through transient previous-turn conflicts", async () => {
  const { retryThreadBusyConflict, FocusAgentRequestError } = loadThreadBusyRetryModule();
  let attempts = 0;
  const result = await retryThreadBusyConflict(async () => {
    attempts += 1;
    if (attempts < 3) {
      throw new FocusAgentRequestError("still processing previous turn", {
        status: 409,
        data: { message: "still processing the previous turn" },
      });
    }
    return "ready";
  });

  assert.equal(result, "ready");
  assert.equal(attempts, 3);
});

test("thread busy retry helper does not retry unrelated errors", async () => {
  const { retryThreadBusyConflict } = loadThreadBusyRetryModule();
  let attempts = 0;

  await assert.rejects(
    retryThreadBusyConflict(async () => {
      attempts += 1;
      throw new Error("network down");
    }),
    /network down/,
  );

  assert.equal(attempts, 1);
});

test("thread busy retry helper cancels when caller scope is stale", async () => {
  const {
    retryThreadBusyConflict,
    ThreadBranchActionRetryCancelled,
    FocusAgentRequestError,
  } = loadThreadBusyRetryModule();
  let attempts = 0;
  let shouldContinue = true;

  await assert.rejects(
    retryThreadBusyConflict(
      async () => {
        attempts += 1;
        shouldContinue = false;
        throw new FocusAgentRequestError("still processing previous turn", {
          status: 409,
          data: { message: "still processing the previous turn" },
        });
      },
      () => shouldContinue,
    ),
    ThreadBranchActionRetryCancelled,
  );

  assert.equal(attempts, 1);
});

test("branch graph node hover AI decision shows only the key conclusion", () => {
  const overlaySource = readFileSync(
    path.join(repoRoot, "apps/web/src/features/branch-tree/branch-tree-detail-overlay.tsx"),
    "utf8",
  );
  const branchTreeCss = readCssModule("apps/web/src/shared/styles/modules/branch-tree.css");
  const compactCss = compactSource(branchTreeCss);

  assert.equal(overlaySource.includes("decisionConclusionText"), true);
  assert.equal(overlaySource.includes("isBranchHandoffDecision"), true);
  assert.equal(overlaySource.includes("Focus Score · 已接收"), true);
  assert.equal(overlaySource.includes("继续在当前新分支处理带入问题"), true);
  assert.equal(overlaySource.includes("建议继续当前线程"), true);
  assert.equal(overlaySource.includes("建议创建子分支"), true);
  assert.equal(overlaySource.includes("建议创建同级分支"), true);
  assert.equal(overlaySource.includes("建议回收分支结论"), true);
  assert.equal(overlaySource.includes("decisionSummary"), true);
  assert.equal(overlaySource.includes("fa-branch-node-ai-decision is-compact"), true);
  assert.equal(overlaySource.includes("fa-branch-node-ai-decision-line"), true);
  assert.equal(overlaySource.includes("fa-branch-node-ai-diagnostic"), false);
  assert.equal(overlaySource.includes("fa-branch-node-ai-audit-note"), false);
  assert.equal(overlaySource.includes("semantic_reason"), false);
  assert.equal(overlaySource.includes("semantic_relatedness"), false);
  assert.equal(overlaySource.includes("semantic_relationship"), false);
  assert.equal(overlaySource.includes("semantic_classifier_status"), false);
  assert.equal(
    overlaySource.includes("Math.round(detailBranchDecision.score * 100)"),
    false,
  );
  assert.equal(overlaySource.includes("detailBranchDecision.rationale"), false);
  assert.equal(compactCss.includes(".fa-branch-node-ai-decision p {"), true);
  assert.equal(compactCss.includes(".fa-branch-node-ai-decision.is-compact {"), true);
  assert.equal(
    compactCss.includes(
      ".fa-branch-node-ai-decision.is-compact .fa-branch-node-ai-decision-line {",
    ),
    true,
  );
  assert.equal(compactCss.includes("-webkit-line-clamp: 1;"), true);
  assert.equal(compactCss.includes("overflow: hidden;"), true);
  assert.equal(compactCss.includes("white-space: nowrap;"), true);
});

test("branch decision summary stays compact while hover details keep diagnostics", () => {
  const diagnostics = loadModule("apps/web/src/shared/branch-decision-diagnostics.ts");
  const summaryPanelSource = readFileSync(
    path.join(repoRoot, "apps/web/src/features/branch-decisions/branch-decision-summary-panel.tsx"),
    "utf8",
  );
  const threadPageContentSource = readFileSync(
    path.join(repoRoot, "apps/web/src/pages/thread/thread-page-content.tsx"),
    "utf8",
  );
  const chatCss = readCssModule("apps/web/src/shared/styles/modules/chat.css");
  const summaryMainSource = summaryPanelSource.split("function BranchDecisionDrawer")[0];
  const drawerSource = summaryPanelSource.split("function BranchDecisionDrawer")[1] ?? "";
  const compactCss = compactSource(chatCss);

  const entries = diagnostics.branchDecisionSemanticDiagnosticEntries({
    metadata: {
      semantic_relatedness: 0.876,
      semantic_relationship: "continuation",
      semantic_reason: "same user goal with no new branch boundary",
      semantic_classifier_status: "matched",
    },
  });

  assert.deepEqual(JSON.parse(JSON.stringify(entries)), [
    { key: "semantic_relatedness", label: "semantic_relatedness", value: "88%" },
    { key: "semantic_relationship", label: "semantic_relationship", value: "continuation" },
    {
      key: "semantic_reason",
      label: "semantic_reason",
      value: "same user goal with no new branch boundary",
    },
    { key: "semantic_classifier_status", label: "semantic_classifier_status", value: "matched" },
  ]);
	  assert.deepEqual(
	    JSON.parse(JSON.stringify(diagnostics.branchDecisionSemanticDiagnosticEntries({
	      diagnostic: {
	        details: {
	          semantic_reason: "classifier unavailable",
          semantic_classifier_status: "fallback",
        },
      },
    }))),
    [
      { key: "semantic_reason", label: "semantic_reason", value: "classifier unavailable" },
	      { key: "semantic_classifier_status", label: "semantic_classifier_status", value: "fallback" },
	    ],
	  );
	  assert.deepEqual(
	    JSON.parse(JSON.stringify(diagnostics.branchDecisionSemanticDiagnosticEntries({
	      metadata: {
	        semantic_reason: "Semantic classifier was not invoked.",
	        semantic_classifier_status: "not_run",
	      },
	    }))),
	    [],
	  );
	  assert.equal(
	    diagnostics.branchDecisionDiagnosticText({
	      metadata: {
	        diagnostic: {
	          gate_reason: "continue_current",
	          mode: "suggest",
	        },
	      },
	    }),
	    "continue_current",
	  );
	  assert.equal(
	    diagnostics.isBranchHandoffDecision({
	      metadata: {
	        source: "branch_handoff",
	        branch_handoff_auto_run: true,
	        handoff_run_status: "interrupted",
	      },
	    }),
	    true,
	  );
	  assert.equal(
	    diagnostics.isBranchHandoffDecision({
	      metadata: {
	        source: "branch_handoff",
	        branch_handoff_auto_run: false,
	      },
	    }),
	    false,
	  );
	  assert.equal(
	    diagnostics.branchHandoffRunStatus({
	      metadata: {
	        source: "branch_handoff",
	        branch_handoff_auto_run: true,
	        handoff_run_status: "interrupted",
	      },
	    }),
	    "interrupted",
	  );
	  assert.equal(summaryPanelSource.includes("branchDecisionSemanticDiagnosticEntries"), true);
	  assert.equal(summaryPanelSource.includes("isBranchHandoffDecision"), true);
	  assert.equal(summaryPanelSource.includes("showAuditNote = auditOnly && !isBranchHandoff"), true);
	  assert.equal(summaryPanelSource.includes('data-handoff={isBranchHandoff ? "true" : undefined}'), true);
	  assert.equal(summaryPanelSource.includes("Focus Score"), true);
	  assert.equal(summaryPanelSource.includes("已接收"), true);
	  assert.equal(summaryPanelSource.includes("继续在当前新分支处理带入问题"), true);
	  assert.equal(
	    summaryPanelSource.includes("新分支已接收带入问题，继续在当前分支处理"),
	    true,
	  );
	  assert.equal(summaryPanelSource.includes("自动生成已中断"), true);
	  assert.equal(summaryPanelSource.includes("!isBranchHandoff"), true);
	  assert.equal(summaryPanelSource.includes("Focus Score"), true);
	  assert.equal(summaryPanelSource.includes("scorePercent(decision.score)"), true);
	  assert.equal(summaryPanelSource.includes('Badge tone="info"'), true);
	  assert.equal(summaryPanelSource.includes('const badgeLabel = "Focus Score"'), true);
	  assert.equal(summaryPanelSource.includes("branchDecisionDetailNote"), true);
	  assert.equal(summaryPanelSource.includes("已生成可确认的分支建议。"), true);
	  assert.equal(
	    summaryPanelSource.includes("A branch recommendation is ready to confirm."),
	    true,
	  );
	  assert.equal(
	    summaryPanelSource.includes("scoreLabel ? <span>{scoreLabel}</span> : null"),
	    true,
	  );
  assert.equal(summaryPanelSource.includes("semanticDiagnosticEntries.map"), false);
  assert.equal(summaryPanelSource.includes("semanticDiagnosticEntries.length > 0"), true);
  assert.equal(summaryMainSource.includes("decision.rationale"), false);
  assert.equal(summaryPanelSource.includes("fa-branch-decision-summary-text"), false);
  assert.equal(drawerSource.includes("decision.rationale"), false);
  assert.equal(summaryPanelSource.includes("fa-branch-decision-signals"), false);
  assert.equal(summaryPanelSource.includes("decision.signals.map"), false);
  assert.equal(summaryPanelSource.includes("fa-branch-decision-summary-trigger"), true);
  assert.equal(summaryPanelSource.includes("aria-controls={detailId}"), true);
  assert.equal(summaryPanelSource.includes("aria-expanded={drawerOpen}"), true);
  assert.equal(summaryPanelSource.includes("fa-branch-decision-summary-details"), true);
  assert.equal(summaryPanelSource.includes("onMouseLeave={() => setDrawerOpen(false)}"), true);
  assert.equal(summaryPanelSource.includes("悬停或点击查看诊断详情"), true);
  assert.match(
    compactSource(threadPageContentSource),
    /<BranchDecisionSummaryPanel .*? \/> <ConversationViewport/s,
  );
  assert.equal(compactCss.includes(".fa-branch-decision-summary-popover:focus-within"), false);
  assert.equal(compactCss.includes('.fa-branch-decision-summary-trigger[data-handoff="true"]'), true);
  assert.equal(compactCss.includes("overflow: hidden;"), true);
  assert.equal(compactCss.includes(".fa-branch-decision-summary-details {"), true);
  assert.equal(compactCss.includes(".fa-branch-decision-summary-popover.is-open"), true);
  assert.equal(compactCss.includes("@media (hover: hover)"), true);
  assert.equal(
    compactCss.includes(".fa-branch-decision-summary-trigger:focus-visible"),
    true,
  );
  assert.equal(compactCss.includes("background-color: var(--fa-panel-1);"), true);
  assert.equal(
    compactCss.includes("background-image: linear-gradient(180deg, var(--fa-panel-2), var(--fa-panel-1));"),
    true,
  );
  assert.equal(compactCss.includes("backdrop-filter: none;"), true);
  assert.equal(compactCss.includes("width: min(520px, calc(100vw - 32px));"), true);
  assert.equal(compactCss.includes("max-height: min(52vh, 420px);"), true);
  assert.equal(compactCss.includes("grid-template-columns: repeat(2, minmax(0, 1fr));"), true);
  assert.equal(compactCss.includes("max-height: 150px;"), true);
  assert.equal(compactCss.includes("-webkit-line-clamp: 2;"), true);
  assert.equal(compactCss.includes("position: absolute;"), true);
  assert.equal(compactCss.includes("justify-content: flex-end;"), true);
  assert.equal(compactCss.includes("bottom: 16px;"), true);
  assert.equal(compactCss.includes("right: 20px;"), true);
  assert.equal(compactCss.includes("bottom: calc(100% + 8px);"), true);
  assert.equal(compactCss.includes("right: 0;"), true);
  assert.equal(compactCss.includes("pointer-events: none;"), true);
  assert.equal(compactCss.includes("pointer-events: auto;"), true);
	  assert.equal(
	    compactCss.includes(
	      ".fa-branch-decision-summary + .fa-conversation-viewport .fa-chat-history { padding-bottom: 56px;",
	    ),
	    true,
	  );
	  assert.equal(compactCss.includes("display: none;"), true);
});

test("chat header keeps conversation tools left and compacts branch actions by available width", () => {
  const headerCss = readFileSync(
    path.join(repoRoot, "apps/web/src/shared/styles/modules/workbench-header.css"),
    "utf8",
  );
  const compactHeaderCss = readFileSync(
    path.join(repoRoot, "apps/web/src/shared/styles/modules/workbench-header-compact.css"),
    "utf8",
  );
  const compactHookSource = readFileSync(
    path.join(repoRoot, "apps/web/src/features/thread/use-thread-header-compact.ts"),
    "utf8",
  );
  const headerButtonsSource = readFileSync(
    path.join(
      repoRoot,
      "apps/web/src/features/thread/thread-header-action-buttons.tsx",
    ),
    "utf8",
  );
  const overridesCss = readFileSync(
    path.join(repoRoot, "apps/web/src/shared/styles/modules/overrides.css"),
    "utf8",
  );
  const conversationToolbarSource = readFileSync(
    path.join(repoRoot, "apps/web/src/features/conversations/conversation-toolbar-view.tsx"),
    "utf8",
  );
  const compactHeader = compactSource(`${headerCss}\n${compactHeaderCss}`);
  const compactHook = compactSource(compactHookSource);
  const compactOverrides = compactSource(overridesCss);

  assert.equal(
    compactHeader.includes(
      ".fa-chat-header-top { display: grid; grid-template-columns: auto minmax(0, 1fr);",
    ),
    true,
  );
  assert.equal(
    compactHeader.includes(
      ".fa-conversation-toolbar { flex: 0 1 auto; justify-content: flex-start;",
    ),
    true,
  );
  assert.equal(
    compactHeader.includes(".fa-chat-header-right-actions { position: relative;"),
    true,
  );
  assert.equal(compactHeader.includes("width: 100%;"), true);
  assert.equal(
    compactHook.includes('actions.closest(".fa-chat-header-right-actions")'),
    true,
  );
  assert.equal(
    compactHook.includes("Math.min(actions.clientWidth, host.clientWidth)"),
    true,
  );
  assert.equal(
    compactHeader.includes(
      ".fa-focus-branches-button:not(.is-renaming) { max-width: clamp(176px, 24vw, 320px); min-width: 0; overflow: hidden;",
    ),
    true,
  );
  assert.equal(
    compactHeader.includes(
      ".fa-focus-branches-button:not(.is-renaming) .fa-toolbar-text { min-width: 0; overflow: hidden; text-overflow: ellipsis;",
    ),
    true,
  );
  assert.equal(
    headerButtonsSource.includes('data-allow-label-truncation="true"'),
    true,
  );
  assert.equal(
    compactHook.includes(
      'button.dataset.allowLabelTruncation === "true"',
    ),
    true,
  );
  assert.equal(compactHook.includes("buttonAllowsLabelTruncation(button)"), true);
  assert.equal(conversationToolbarSource.includes("fa-conversation-jump-icon"), true);
  assert.equal(
    conversationToolbarSource.includes("ICON_CONVERSATION_SWITCHER_QUERY"),
    true,
  );
  assert.equal(
    conversationToolbarSource.includes("fa-conversation-switcher-icon"),
    true,
  );
  assert.equal(
    conversationToolbarSource.includes(
      "ChatBubbleIcon style={ICON_CONVERSATION_SWITCHER_STYLES.svg}",
    ),
    true,
  );
  assert.equal(compactOverrides.includes("@media (max-width: 520px)"), false);
  assert.equal(
    conversationToolbarSource.includes('gridTemplateColumns: "34px"'),
    true,
  );
  assert.equal(
    conversationToolbarSource.includes('textIndent: "100%"'),
    true,
  );
});
