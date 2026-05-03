import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import path from "node:path";
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
  const reducerSnippet = ["createInitialStreamState", "upsertBranchAction", "reduceStreamEvent"]
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
	const sourceText = readFileSync(
		path.join(repoRoot, "apps/web/src/entities/messages/message-transcript.ts"),
		"utf8",
  );
  const functionNames = [
    "normalizeMessageType",
    "normalizeText",
    "looksLikeInternalToolMarkup",
    "looksLikeToolPlanningPayload",
    "shouldHideStreamingInternalContent",
    "totalTokensFromUsageMetadata",
    "truncateText",
    "parseJsonValue",
    "extractToolSummaryCandidate",
    "summarizeToolResult",
		"formatToolDetailContent",
		"uniqueToolNames",
		"visibleAssistantIndexesToHide",
		"buildTranscriptItems",
	];
  const snippet = functionNames.map((name) => extractFunction(sourceText, name)).join("\n\n");
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
		path.join(
			repoRoot,
			"apps/web/src/features/trajectory-observability/trajectory-utils.ts",
		),
		"utf8",
	);
	const functionNames = [
		"visiblePreviewText",
		"extractStructuredSummary",
		"compactSnippet",
	];
	const snippet = functionNames
		.map((name) => extractFunction(sourceText, name))
		.join("\n\n");
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
	assert.equal(looksLikeTextualToolCallArtifact("[背景] 沪指本周震荡。"), false);
	assert.equal(looksLikeTextualToolCallArtifact("我来帮你分析这份报告：结论是现金流改善。"), false);
	assert.equal(safeVisibleText("[web_search] searching"), "");
	assert.equal(safeVisibleText("**[web_fetch]** 尝试通过东方财富API获取数据。"), "");
	assert.equal(safeVisibleText("让我尝试获取更详细的日线数据："), "");
	assert.equal(safeVisibleText("如果没有新指示，我将默认继续执行。请确认是否继续。"), "");

  const withArtifactDelta = reduceStreamEvent(createInitialStreamState(), {
    event: "message.delta",
    data: {
      delta: "[web_fetch] 尝试获取沪指数据，请稍等。",
      channel: "visible_text",
    },
  });
  assert.equal(withArtifactDelta.visibleText, "");

  const withPlainDelta = reduceStreamEvent(withArtifactDelta, {
    event: "visible_text.delta",
    data: {
      delta: "沪指本周震荡回稳。",
      channel: "visible_text",
    },
  });
  assert.equal(withPlainDelta.visibleText, "沪指本周震荡回稳。");

  const withInternalProcessDelta = reduceStreamEvent(withPlainDelta, {
    event: "visible_text.delta",
    data: {
      delta: "我来帮你查询华钰矿业（601020）近一周的行情数据。请确认是否继续。",
      channel: "visible_text",
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

test("stream reducer tracks branch action lifecycle events", () => {
  const { createInitialStreamState, reduceStreamEvent } = loadSdkStreamFunctions();
  const proposed = {
    action_id: "branch-action-1",
    kind: "fork_sibling_branch",
    status: "pending",
    root_thread_id: "root-1",
    source_thread_id: "child-1",
    target_parent_thread_id: "root-1",
    suggested_branch_name: "华英农业",
    branch_role: "explore_alternatives",
    reason: "User requested branch switch.",
    created_at: "2026-04-26T00:00:00+00:00",
  };

  const pending = reduceStreamEvent(createInitialStreamState(), {
    event: "branch.action.proposed",
    data: { thread_id: "child-1", branch_action: proposed },
  });
  assert.equal(pending.branchActions.length, 1);
  assert.equal(pending.branchActions[0].status, "pending");

  const executed = reduceStreamEvent(pending, {
    event: "branch.action.executed",
    data: {
      thread_id: "child-1",
      branch_action: {
        ...proposed,
        status: "executed",
        navigation: { root_thread_id: "root-1", thread_id: "child-2" },
      },
    },
  });
  assert.equal(executed.branchActions.length, 1);
  assert.equal(executed.branchActions[0].status, "executed");
  assert.equal(executed.branchActions[0].navigation.thread_id, "child-2");
});

test("SSE parser ignores trailing blank frames after stream completion", () => {
  const { parseSSEFrames } = loadModule("frontend-sdk/src/parser.ts");

  const parsed = parseSSEFrames(
    'event: visible_text.completed\ndata: {"content":"done"}\n\n\n\n',
  );

  assert.equal(parsed.frames.length, 1);
  assert.equal(parsed.frames[0].event, "visible_text.completed");
  assert.equal(parseSSEFrames("\n\n").frames.length, 0);
});

test("message list does not render trailing tool output as a fake assistant reply", () => {
  const sourceText = readFileSync(
    path.join(repoRoot, "apps/web/src/entities/messages/message-transcript.ts"),
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
  } = loadFunctions("apps/web/src/features/thread-stream/message-composer.tsx", [
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

test("context meter formats current context usage separately from token spend", () => {
  const {
    contextUsagePercent,
    contextUsageRemainingPercent,
    contextUsageTone,
    formatContextMarkerCount,
    shouldShowContextCompactAction,
  } = loadFunctions("apps/web/src/features/thread-stream/message-composer.tsx", [
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
