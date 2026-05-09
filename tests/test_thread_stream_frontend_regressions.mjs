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
  const snippet = functionNames.map((name) => extractFunction(sourceText, name)).join("\n\n");
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
    "buildTranscriptItems",
  ];
  const snippet = functionNames.map((name) => extractFunction(sources, name)).join("\n\n");
  const transpiled = ts.transpileModule(
    `function looksLikeTextualToolCallArtifact(value) { return String(value ?? "").includes("<tool_call"); }\n\n${snippet}`,
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
  vm.runInNewContext(`${transpiled}\nmodule.exports = { buildTranscriptItems };`, context);
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

  assert.equal(looksLikeTextualToolCallArtifact("[web_fetch] 尝试获取沪指数据，请稍等。"), true);
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
  assert.equal(looksLikeTextualToolCallArtifact("function=web_search>"), true);
  assert.equal(looksLikeTextualToolCallArtifact("<parameter=query>比亚迪</parameter>"), true);
  assert.equal(looksLikeTextualToolCallArtifact("[背景] 沪指本周震荡。"), false);
  assert.equal(looksLikeTextualToolCallArtifact("我来帮你分析这份报告：结论是现金流改善。"), false);
  assert.equal(safeVisibleText("</tool_call>"), "");
  assert.equal(safeVisibleText("function=web_search>"), "");
  assert.equal(safeVisibleText("[web_search] searching"), "");
  assert.equal(safeVisibleText("**[web_fetch]** 尝试通过东方财富API获取数据。"), "");
  assert.equal(safeVisibleText("让我尝试获取更详细的日线数据："), "");
  assert.equal(safeVisibleText("如果没有新指示，我将默认继续执行。请确认是否继续。"), "");

  const withArtifactDelta = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "[web_fetch] 尝试获取沪指数据，请稍等。",
      channel: "message",
    },
  });
  assert.equal(withArtifactDelta.visibleText, "");

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

  const withArtifactCompleted = reduceStreamEvent(withPlainDelta, {
    event: "message.completed",
    data: {
      content: "[web_fetch] 继续获取数据。",
    },
  });
  assert.equal(withArtifactCompleted.visibleText, "");
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

  assert.equal(messageListSource.includes("toolApprovalInterrupts.map"), true);
  assert.equal(approvalCardSource.includes("onDecide?.(interrupt, true)"), true);
  assert.equal(approvalCardSource.includes("onDecide?.(interrupt, false)"), true);
  assert.equal(approvalCardSource.includes("interrupt.redacted_args"), true);
  assert.equal(approvalCardSource.includes("interrupt.args"), false);
  assert.equal(threadPageSource.includes("handleDecideToolApproval"), true);
  assert.equal(streamHookSource.includes("client.streamResume"), true);
  assert.equal(streamHookSource.includes("createToolApprovalDecision(interrupt, approved)"), true);
  assert.equal(streamHookSource.includes("activeRunIdsRef"), true);
  assert.equal(streamHookSource.includes("client.cancelHarnessRun(runId, { action: \"interrupt\" })"), true);
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
	assert.equal(toolItems.length, 2);
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
