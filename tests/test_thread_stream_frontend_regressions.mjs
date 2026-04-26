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

test("request cleanup clears the optimistic user message after failed sends", () => {
  const {
    createThreadStreamEntry,
    nextThreadEntryMap,
    patchThreadEntry,
    resolveStreamRequestCleanup,
    resolveThinkingModeForRequest,
  } = loadFunctions(
    "apps/web/src/features/thread-stream/use-thread-stream.ts",
    [
      "resolveStreamRequestCleanup",
      "resolveThinkingModeForRequest",
      "createThreadStreamEntry",
      "nextThreadEntryMap",
      "patchThreadEntry",
    ],
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
  assert.equal(looksLikeTextualToolCallArtifact("[背景] 沪指本周震荡。"), false);
  assert.equal(safeVisibleText("[web_search] searching"), "");

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

test("message list does not render trailing tool output as a fake assistant reply", () => {
  const sourceText = readFileSync(
    path.join(repoRoot, "apps/web/src/entities/messages/message-list.tsx"),
    "utf8",
  );

  assert.equal(sourceText.includes("assistant-message-fallback"), true);
  assert.equal(sourceText.includes("lastItem.id}-summary"), false);
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
