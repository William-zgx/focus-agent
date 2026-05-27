# Android App

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

## Included Modules

The Android target keeps the mobile surfaces focused on local conversation and
administration while preserving the non-Agent-Team runtime surfaces:

- Chat, conversations, threads, Focus Score, branch actions, and merge review.
- Account, login, registration, sessions, users, audit events, and config.
- Agent governance, memory, and observability routes backed by local app data.
- Local `web_search` tool-call streaming for current web lookups.

The Android target disables only the Agent Team workbench and productivity routes
via feature flags. The Web target continues to include them by default.
