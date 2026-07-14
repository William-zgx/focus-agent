# Android App

Updated: 2026-07-14

The Android shell is a Capacitor wrapper around the existing Web app, plus a
**device-local single-user runtime** under `apps/web/src/android-local-runtime/`
that uses the SDK local transport. It is an optional product surface of the
self-hosted workbench platform—not a thin mirror of every Web module. Platform
positioning: [project-overview.md](project-overview.md).

Web builds keep the normal `/app` base path and all Web modules enabled.
Android-only behavior is selected by `pnpm android:web:build`, which sets
`VITE_FOCUS_AGENT_TARGET=android` (and typically disables Agent Workbench /
Productivity for the Android bundle).

## Build

The debug workflow rebuilds the Android-targeted Web bundle, synchronizes the
Capacitor project, and then assembles the APK:

```bash
pnpm android:apk:debug
```

Android-targeted assets are written to `apps/web/dist-android`; the normal Web
bundle remains in `apps/web/dist`. Capacitor synchronizes only the Android
directory. This separation prevents Android build/sync commands from replacing
the `/app`-based Web bundle that FastAPI serves, and allows Web and Android
builds to run concurrently without sharing an output directory.

The debug APK is written to:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

`pnpm android:open` also runs `android:sync` before opening Android Studio so
the native project cannot be opened with stale Web assets.

### Release Signing And Versioning

Release builds fail closed unless all signing values are supplied. The build
does not fall back to the debug key and does not emit an unsigned release APK.
Inject the following values through environment variables or same-named Gradle
properties (`-P...`):

| Name | Purpose |
| --- | --- |
| `FOCUS_AGENT_ANDROID_KEYSTORE_PATH` | Absolute path, or a path relative to `android/`, to the release keystore |
| `FOCUS_AGENT_ANDROID_KEYSTORE_PASSWORD` | Keystore password |
| `FOCUS_AGENT_ANDROID_KEY_ALIAS` | Signing key alias |
| `FOCUS_AGENT_ANDROID_KEY_PASSWORD` | Signing key password |
| `FOCUS_AGENT_ANDROID_VERSION_CODE` | Optional positive integer; defaults to `1` |
| `FOCUS_AGENT_ANDROID_VERSION_NAME` | Optional display version; defaults to `1.0` |

Do not put signing passwords, private keys, or production keystores in this
repository. A release build can be run without exposing values on the command
line:

```bash
export FOCUS_AGENT_ANDROID_KEYSTORE_PATH=/secure/path/focus-agent-release.jks
export FOCUS_AGENT_ANDROID_KEYSTORE_PASSWORD='...'
export FOCUS_AGENT_ANDROID_KEY_ALIAS=focus-agent
export FOCUS_AGENT_ANDROID_KEY_PASSWORD='...'
export FOCUS_AGENT_ANDROID_VERSION_CODE=42
export FOCUS_AGENT_ANDROID_VERSION_NAME=1.4.0

pnpm android:sync
(cd android && ./gradlew assembleRelease)
```

Verify the resulting signature with the Android SDK tool:

```bash
apksigner verify --verbose --print-certs \
  android/app/build/outputs/apk/release/app-release.apk
```

### Deep Links

The Android manifest registers the custom `focusagent://app/...` scheme.
The native `FocusAgentAppPlugin` captures the cold-start launch intent and
exposes its URL through `getLaunchUrl()` exactly once. That launch intent is not
delivered again as a hot event. Each later accepted `ACTION_VIEW` intent is
delivered at most once as a retained Capacitor `appUrlOpen` event, so a listener
that is still registering does not lose the link and a repeated delivery of the
same intent object does not navigate twice.

Both cold and hot URLs are mapped to an allowlist of internal routes. External
schemes, a host other than `app`, URLs with credentials or a port, encoded path
separators, and unknown paths are ignored.
The app does not process query strings or fragments for routing. Examples:

```text
focusagent://app/
focusagent://app/admin/config
focusagent://app/c/<conversation-id>/t/<thread-id>
focusagent://app/c/<conversation-id>/t/<thread-id>/review
```

Test a link on a connected emulator or device:

```bash
adb shell am start -W \
  -a android.intent.action.VIEW \
  -d 'focusagent://app/admin/config' \
  ai.focusagent.app
```

## Local Runtime

The bundled Android app uses an in-app local Focus Agent runtime instead of an
HTTP backend. It is a device-local, single-user runtime: there are no user
accounts, passwords, login/registration flows, bearer tokens, sessions, or
administrator roles. The app exposes one local principal only to keep shared
SDK contracts working; it has no roles and is not an administrator.

Chat, conversations, branches, Focus Score branch routing, Branch Action
recommendations, merge review, model metadata, device-local configuration, and
local memory/governance/observability compatibility routes are served by the
app-local SDK transport. User/account management and audit-governance endpoints
are unavailable in Android local mode. Requests carrying an authorization
header are rejected rather than treated as a local login.

Model calls are made directly from the app to the configured model provider.
The default Android local provider is DeepSeek at `https://api.deepseek.com`
with model `deepseek-v4-pro`. The configuration screen is a device-local
settings surface, not an administrator console: use it to save model-provider
settings and an API key for this device. The native secure-storage plugin
encrypts the serialized model secrets with an AES-GCM key held by Android
Keystore and stores the encrypted IV/ciphertext envelope in private app
preferences. The API key is excluded from WebView local storage and is never
sent to a Focus Agent backend.

Direct provider calls use the native `FocusAgentCancellableHttp` plugin rather
than an unbounded executor:

- A fixed pool runs at most 4 requests concurrently.
- The bounded queue holds at most 4 additional requests, for at most 8 active
  running-or-queued request IDs. Further submissions fail without entering the
  queue.
- Response bodies are capped at 2 MiB before UTF-8 decoding. Redirect following
  is disabled.
- Cancelling a request disconnects its `HttpURLConnection`, cancels its queued
  or running future, and rejects the plugin call as cancelled.
- Destroying the plugin cancels every tracked request and shuts down the
  executor, so work does not outlive the WebView bridge.

Cancellation applies to direct model-provider calls; it does not imply that an
upstream provider completed no work before the connection was aborted.

Release-targeted Web bundles accept only HTTPS model-provider URLs. Debug
workflows (`android:run` and `android:apk:debug`) explicitly enable HTTP only
for the Android emulator host loopback addresses `10.0.2.2` and `10.0.3.2`.
The debug network security config denies cleartext traffic by default and
allows only those two hosts. Device, non-emulator, and production provider
URLs must use HTTPS.

`capacitor.config.ts` sets Android `loggingBehavior` to `none`. Synced debug and
release projects therefore disable Capacitor's native bridge call/result
payload logging, including payloads crossing the cancellable HTTP and secure
storage plugins. This is bridge logging hardening, not a claim that every
application or WebView console message is suppressed. Capacitor WebView
debugging remains controlled by the Android build type rather than being
globally enabled in the project config.

The Android-local configuration surface mirrors only device-local settings:
model provider settings, tool availability, Skill global and per-skill
enablement, and policy compatibility fields. Non-secret configuration is kept
in WebView local state. Android does not manage remote MCP servers;
MCP-related workflows appear through installed/local skills and tool
compatibility data.

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
| `auth-conversation-runtime.ts` | Device-local principal, conversations, and thread state; rejects account and session operations |
| `thread-branch-routes.ts` / `branch-logic.ts` | Branch tree, branch actions, merge review, thread resolution, and branch decisions |
| `agent-runtime.ts` | Governance policies, skill catalog/selection/preference compatibility data, delegation/model-router/task-ledger compatibility data, and feedback trend route |
| `memory-observability-runtime.ts` | Local memory, context, trajectory, overview, replay, and promote compatibility routes |
| `admin-runtime.ts` | Device-local model, tool, Skill, and policy configuration; user and audit governance is unavailable |
| `model-provider.ts` / `model-runtime.ts` | Provider metadata, secure API key lookup, direct OpenAI-compatible model calls, and native request cancellation |
| `stream-runtime.ts` / `sse.ts` | POST-based stream events, local tool events, branch recommendation short-circuiting, and SSE framing |
| `web-search.ts` / `web-planning.ts` / `web-fetch.ts` | Android-local web search planning and fetch helpers |
| `workspace-runtime.ts` / `local-tool-execution.ts` / `local-tool-planning.ts` | Local tool planning and guarded workspace/tool execution compatibility |
| `state.ts`, `types.ts`, `helpers.ts`, `constants.ts` | Local storage schema, shared types, response helpers, and storage keys |

The native boundary is registered by `MainActivity`:

| Plugin | Responsibility |
| --- | --- |
| `FocusAgentAppPlugin` | One-shot cold launch URL consumption and one-delivery hot `appUrlOpen` intents |
| `FocusAgentCancellableHttpPlugin` | Bounded HTTPS provider transport, response-size enforcement, cancellation, and lifecycle shutdown |
| `FocusAgentSecureStoragePlugin` | Android Keystore-backed AES-GCM storage for model secrets |

## Included Modules

The Android target keeps the mobile surfaces focused on local conversation and
device configuration while preserving the non-Agent-Team runtime surfaces:

- Chat, conversations, threads, Focus Score, branch actions, and merge review.
- Device-local model, tool, Skill, and policy configuration.
- Agent governance, memory, and observability routes backed by local app data.
- Local `web_search` tool-call streaming for current web lookups.

The Android target disables the Agent Team workbench, productivity routes, and
account/user/audit administration routes. The Web target continues to include
those server-backed capabilities by default.

## Verification

Run the local runtime smoke after changing SDK endpoint wiring, stream reducer
behavior, Android routes, model-provider storage, Admin settings, Skill
preference/config behavior, local web search, or the module facade:

```bash
make frontend-android-runtime-smoke
```

Run the focused scaffold checks and Android builds with:

```bash
.venv/bin/python -m pytest \
  tests/test_android_app_scaffold.py \
  tests/test_capacitor_bridge_logging_security.py -q
pnpm android:runtime:smoke
pnpm android:apk:debug
pnpm android:sync
(cd android && ./gradlew assembleRelease)
```

The last command is expected to fail with `Release signing is incomplete`
unless all four signing values are injected.

For broader Web/Android refactors, prefer:

```bash
make frontend-qa
```

That bundle adds full Web/SDK checks, style governance, bundle budget,
architecture report, and compatibility inventory around the Android smoke.

### CI And Emulator Boundary

The repository GitHub Actions Android job runs:

```bash
pnpm android:sync:debug
(cd android && ./gradlew --no-daemon assembleDebug lintDebug testDebugUnitTest)
```

This verifies Web asset synchronization, debug compilation, Android lint, and
host-side JVM unit tests. It intentionally does **not** boot an emulator or run
`connectedDebugAndroidTest`; passing the normal CI job is therefore not evidence
of device lifecycle, Android network-policy, or retained `appUrlOpen` behavior.

For changes to native cancellation, deep links, secure storage, network policy,
or activity/plugin lifecycle, start an API 36 emulator (or connect a compatible
device), then run the instrumentation layer explicitly:

```bash
pnpm android:sync:debug
(cd android && ./gradlew connectedDebugAndroidTest)
```

Also exercise at least one cold-start deep link and one hot deep link with
`adb shell am start`, and cancel an in-flight provider request. Release signing,
release-only manifest behavior, and real provider TLS still require a signed
release candidate or equivalent device validation; emulator instrumentation
does not replace those checks.
