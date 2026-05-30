# Android App

Updated: 2026-05-30

The Android shell is a Capacitor wrapper around the existing Web app. Web builds
keep the normal `/app` base path and all Web modules enabled. Android-only
behavior is selected by `pnpm android:web:build`, which sets
`VITE_FOCUS_AGENT_TARGET=android`.

## Build

```bash
pnpm android:apk:debug
```

The debug APK is written to:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

## Local Runtime

The bundled Android app uses an in-app local Focus Agent runtime instead of an
HTTP backend. Chat, conversations, branches, Focus Score branch routing,
Branch Action recommendations, merge review, account, sessions, users, audit
events, config, model metadata, local memory/governance/observability
compatibility routes, and Android-local web search tool events are served by the
app-local SDK transport.

Model calls are made directly from the app to the configured model provider.
The default Android local provider is DeepSeek at `https://api.deepseek.com`
with model `deepseek-v4-pro`. Open the Admin config screen and save the provider
API key in the local API key field. The key is stored through the native secure
storage plugin and is never sent to a Focus Agent backend.

The Web target is unchanged and continues to use the SDK default HTTP transport
for `/v1` and `/v2` backend routes. Android local data is persisted in the app
WebView's local storage.

## Runtime Module Map

The Android local runtime lives in `apps/web/src/android-local-runtime/`.
`local-focus-agent-runtime.ts` is the public facade consumed by
`shared/sdk/focus-agent-provider.tsx`; feature behavior is split into narrow
modules so Web transport code and Android-only local behavior stay separated.

| Module | Responsibility |
| --- | --- |
| `local-v1-runtime.ts` | Local route dispatcher for `/v1` and `/v2` compatible endpoints |
| `auth-conversation-runtime.ts` | Login, demo tokens, sessions, users, conversations, and thread state |
| `thread-branch-routes.ts` / `branch-logic.ts` | Branch tree, branch actions, merge review, thread resolution, and branch decisions |
| `agent-runtime.ts` | Governance policies, skill catalog/selection, delegation/model-router/task-ledger compatibility data, and feedback trend route |
| `memory-observability-runtime.ts` | Local memory, context, trajectory, overview, replay, and promote compatibility routes |
| `admin-runtime.ts` | Admin config, users, audit events, roles, status, sessions, and password reset |
| `model-provider.ts` / `model-runtime.ts` | Provider metadata, secure API key lookup, and direct OpenAI-compatible model calls |
| `stream-runtime.ts` / `sse.ts` | POST-based stream events, local tool events, branch recommendation short-circuiting, and SSE framing |
| `web-search.ts` / `web-planning.ts` / `web-fetch.ts` | Android-local web search planning and fetch helpers |
| `workspace-runtime.ts` / `local-tool-execution.ts` / `local-tool-planning.ts` | Local tool planning and guarded workspace/tool execution compatibility |
| `state.ts`, `types.ts`, `helpers.ts`, `constants.ts` | Local storage schema, shared types, response helpers, and storage keys |

## Included Modules

The Android target keeps the mobile surfaces focused on local conversation and
administration while preserving the non-Agent-Team runtime surfaces:

- Chat, conversations, threads, Focus Score, branch actions, and merge review.
- Account, login, registration, sessions, users, audit events, and config.
- Agent governance, memory, and observability routes backed by local app data.
- Local `web_search` tool-call streaming for current web lookups.

The Android target disables only the Agent Team workbench and productivity routes
via feature flags. The Web target continues to include them by default.

## Verification

Run the local runtime smoke after changing SDK endpoint wiring, stream reducer
behavior, Android routes, model-provider storage, local web search, or the module
facade:

```bash
make frontend-android-runtime-smoke
```

For broader Web/Android refactors, prefer:

```bash
make frontend-qa
```

That bundle adds full Web/SDK checks, style governance, bundle budget,
architecture report, and compatibility inventory around the Android smoke.
