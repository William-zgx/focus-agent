# Focus Agent Web SDK

The Focus Agent Web SDK is a typed TypeScript client for consuming the Focus Agent HTTP and SSE streaming protocol from browser or Node environments.

It is meant for teams that want a small integration surface instead of re-implementing POST-based SSE parsing, event typing, and stream state accumulation in every frontend.

- Main project README: [`../README.md`](../README.md)
- Chinese README: [`../README.zh-CN.md`](../README.zh-CN.md)

## Why This SDK Exists

Focus Agent streams more than a final assistant message. A real client often needs to deal with:

- token-by-token visible text updates
- separate reasoning and tool-call channels
- tool lifecycle events
- terminal turn states
- authenticated POST requests that return SSE streams

This SDK packages those concerns into a small, typed client layer.

## Features

- `FocusAgentClient` for authenticated JSON requests and POST-based SSE streaming
- Conversation, branch tree, branch action, and merge review request helpers
- Trajectory observability helpers for overview/list/detail/stats/replay/promote flows
- Strongly typed event names and payloads
- SSE parser for `fetch(..., { method: "POST" })` response bodies
- Reducer helpers for accumulating stream state
- Type guards for common event routing paths
- `FocusAgentRequestError` for structured HTTP failure handling
- Compatibility support for older `message.*` event names alongside `visible_text.*`

## Package Layout

- `src/client.ts` - typed HTTP and SSE client
- `src/types.ts` - request, response, event, branch, and stream state types
- `src/parser.ts` - low-level SSE frame parsing and event decoding
- `src/reducers.ts` - stream state helpers for UI state accumulation
- `src/guards.ts` - convenient event type guards
- `src/index.ts` - public exports

## Install And Build

This package currently lives inside the main repository and is built locally:

```bash
cd frontend-sdk
npm install
npm run check
npm run build
```

Requirements:

- Node.js 20+
- A Focus Agent server to connect to

## Quick Start

```ts
import { FocusAgentClient } from "@focus-agent/web-sdk";

const client = new FocusAgentClient({
  baseUrl: "http://127.0.0.1:8000",
});

const token = await client.createDemoToken({ user_id: "researcher-1" });
client.setToken(token.access_token);

const stream = await client.streamTurn({
  thread_id: "main-1",
  message: "Research this topic and branch only if needed.",
});

const finalState = await client.collectStream(stream, {
  onVisibleTextDelta(event) {
    console.log("visible", event.data.delta);
  },
  onReasoningDelta(event) {
    console.log("reasoning", event.data.delta);
  },
  onToolCallDelta(event) {
    console.log("tool-call", event.data.name, event.data.args_delta);
  },
  onToolEvent(event) {
    console.log("tool", event.event, event.data.tool_name);
  },
  onCompleted(event) {
    console.log("completed", event.data.thread_state);
  },
});

console.log(finalState.visibleText);
```

## Client API

`FocusAgentClient` currently exposes these main methods:

- `createDemoToken()` - request a local development token
- `getPrincipal()` - inspect the authenticated principal
- `listModels()` - fetch the current model catalog
- `listConversations()`, `createConversation()`, `renameConversation()`, `archiveConversation()`, `activateConversation()` - manage conversation shells
- `getThreadState()` - fetch the current thread payload used by the app
- `getBranchTree()` - fetch the branch tree rooted at a conversation
- `forkBranch()`, `renameBranch()`, `archiveBranch()`, `activateBranch()` - manage branch records
- `prepareMergeProposal()` and `applyMergeDecision()` - drive merge review workflows
- `getObservabilityOverview()`, `listTrajectoryTurns()`, `getTrajectoryTurn()`, and `getTrajectoryStats()` - inspect runtime readiness and Postgres-backed trajectory observability data
- `replayTrajectoryTurn()` and `promoteTrajectoryTurn()` - preview replay and dataset promotion payloads for a trajectory turn
- `streamTurn()` - stream a new chat turn
- `streamResume()` - continue from an interrupt or resume payload
- `collectStream()` - iterate a stream and accumulate a final derived state
- `setToken()` - update the bearer token in memory

Authentication can be provided either by:

- passing `token` in the constructor
- calling `setToken(...)`
- providing `getToken()` for lazy or async token resolution

You can also override `fetch` with `fetchImpl` when integrating in custom runtimes or tests.

`streamTurn()` and `streamResume()` also accept an optional `AbortSignal` wrapper so UI code can cancel in-flight streams cleanly.

## Event Model

Common event families:

- `visible_text.*`
- `message.*`
- `reasoning.*`
- `tool_call.delta`
- `tool.call.delta`
- `tool.*`
- `task.*`
- `turn.*`
- `agent.update`

Recommended usage:

- Normal chat UI: render `visible_text.delta` and `visible_text.completed`
- Debug panels: also render `reasoning.*`
- Tooling consoles: consume `tool_call.*`, `tool.*`, and `task.*`
- Completion handling: watch `turn.completed`, `turn.failed`, and `turn.closed`

The SDK keeps compatibility with older servers or clients by treating `message.delta` and `message.completed` as visible-text equivalents.

## Reducers And Guards

The package includes lightweight helpers for common UI wiring.

Reducer helpers:

- `createInitialStreamState()`
- `reduceStreamEvent()`

The derived stream state tracks:

- `visibleText`
- `reasoningText`
- `toolCalls`
- `toolEvents`
- `latestTurnState`
- `isClosed`
- `failed`

Type guards:

- `isVisibleTextDeltaEvent()`
- `isReasoningDeltaEvent()`
- `isToolCallDeltaEvent()`
- `isToolLifecycleEvent()`
- `isTerminalEvent()`

## Low-Level Streaming

If you want to build your own state store, you can work directly with the lower-level parser utilities:

- `parseSSEFrames()` - split raw SSE text into parsed frames
- `decodeEvent()` - decode a parsed frame into a typed event
- `iterSSEEvents()` - iterate `ReadableStream<Uint8Array>` as Focus Agent events

This is useful when you want custom buffering, tracing, analytics, or framework-specific adapters.

## Example Integration Pattern

```ts
import {
  FocusAgentClient,
  createInitialStreamState,
  reduceStreamEvent,
  isTerminalEvent,
} from "@focus-agent/web-sdk";

const client = new FocusAgentClient({
  baseUrl: "http://127.0.0.1:8000",
  getToken: async () => localStorage.getItem("focus-agent-token"),
});

const stream = await client.streamTurn({
  thread_id: "main-1",
  message: "Summarize the current branch state.",
});

let state = createInitialStreamState();

for await (const event of stream) {
  state = reduceStreamEvent(state, event);

  if (isTerminalEvent(event)) {
    break;
  }
}
```

## Development

Common local commands:

```bash
cd frontend-sdk
npm install
npm run check
npm run build
```

From the repository root:

```bash
make sdk-install
make sdk-check
make sdk-build
```

## Notes

- This SDK is intentionally small and focused on the current Focus Agent protocol.
- Branch, conversation, merge proposal, imported-conclusion, and trajectory observability types are exported from `src/types.ts` for frontend consumers.
- HTTP request failures throw `FocusAgentRequestError`, which includes `status` and `statusText`.
