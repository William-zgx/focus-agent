import json
import re
from pathlib import Path


def _android_local_runtime_text(web_root: Path) -> str:
    runtime_root = web_root / "src" / "android-local-runtime"
    return "\n".join(path.read_text() for path in sorted(runtime_root.glob("*.ts")))


def test_android_app_scaffold_builds_capacitor_shell():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web"
    android_root = root / "android"

    required = [
        root / "capacitor.config.ts",
        android_root / "app" / "build.gradle",
        android_root / "app" / "src" / "main" / "AndroidManifest.xml",
        android_root
        / "app"
        / "src"
        / "main"
        / "java"
        / "ai"
        / "focusagent"
        / "app"
        / "MainActivity.java",
        android_root / "app" / "src" / "debug" / "AndroidManifest.xml",
        android_root
        / "app"
        / "src"
        / "debug"
        / "res"
        / "xml"
        / "debug_network_security_config.xml",
        web_root / "src" / "android-local-runtime" / "local-focus-agent-runtime.ts",
    ]

    for path in required:
        assert path.exists(), f"missing {path}"

    package_json = json.loads((root / "package.json").read_text())
    scripts = package_json["scripts"]
    assert scripts["android:web:build"].startswith("VITE_FOCUS_AGENT_TARGET=android ")
    assert "VITE_FOCUS_AGENT_APP_BASE=/" in scripts["android:web:build"]
    assert "VITE_FOCUS_AGENT_ROUTER_BASE=/" in scripts["android:web:build"]
    assert "VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH=false" in scripts["android:web:build"]
    assert "VITE_FOCUS_AGENT_ENABLE_PRODUCTIVITY=true" not in scripts["android:web:build"]
    assert "VITE_FOCUS_AGENT_ENABLE_PRODUCTIVITY=false" in scripts["android:web:build"]
    assert scripts["android:apk:debug"] == (
        "pnpm android:sync && cd android && ./gradlew assembleDebug"
    )
    assert (
        scripts["android:runtime:smoke"]
        == "pnpm --filter @focus-agent/web-app smoke:android-local-runtime"
    )
    assert package_json["dependencies"]["@capacitor/android"]
    assert package_json["dependencies"]["@capacitor/core"]
    assert package_json["devDependencies"]["@capacitor/cli"]

    capacitor_config = (root / "capacitor.config.ts").read_text()
    assert 'appId: "ai.focusagent.app"' in capacitor_config
    assert 'appName: "Focus Agent"' in capacitor_config
    assert 'webDir: "apps/web/dist"' in capacitor_config
    assert "CapacitorHttp" in capacitor_config
    assert "enabled: true" in capacitor_config
    assert 'androidScheme: "http"' in capacitor_config

    android_build = (android_root / "app" / "build.gradle").read_text()
    assert 'namespace = "ai.focusagent.app"' in android_build
    assert 'applicationId "ai.focusagent.app"' in android_build

    android_manifest = (android_root / "app" / "src" / "main" / "AndroidManifest.xml").read_text()
    assert "android.permission.INTERNET" in android_manifest
    assert 'android:allowBackup="false"' in android_manifest
    assert 'android:fullBackupContent="false"' in android_manifest

    main_activity = (
        android_root
        / "app"
        / "src"
        / "main"
        / "java"
        / "ai"
        / "focusagent"
        / "app"
        / "MainActivity.java"
    ).read_text()
    secure_storage_plugin = (
        android_root
        / "app"
        / "src"
        / "main"
        / "java"
        / "ai"
        / "focusagent"
        / "app"
        / "FocusAgentSecureStoragePlugin.java"
    ).read_text()
    assert "FocusAgentSecureStoragePlugin.class" in main_activity
    assert '@CapacitorPlugin(name = "FocusAgentSecureStorage")' in secure_storage_plugin
    assert "AndroidKeyStore" in secure_storage_plugin
    assert "AES/GCM/NoPadding" in secure_storage_plugin

    debug_manifest = (android_root / "app" / "src" / "debug" / "AndroidManifest.xml").read_text()
    assert "android:usesCleartextTraffic" in debug_manifest
    assert "debug_network_security_config" in debug_manifest


def test_android_target_uses_local_runtime_and_excludes_agent_team():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web"

    env_text = (web_root / "src" / "shared" / "config" / "env.ts").read_text()
    assert 'VITE_FOCUS_AGENT_TARGET || "web"' in env_text
    assert 'target === "android"' in env_text
    assert "API_BASE_URL_STORAGE_KEY" in env_text
    assert "readStoredApiBaseUrl" in env_text
    assert "persistApiBaseUrl" in env_text
    assert "LOCAL_RUNTIME_API_BASE_URL" in env_text
    assert "const useLocalRuntime = isAndroidTarget" in env_text
    assert "return LOCAL_RUNTIME_API_BASE_URL" in env_text
    assert "apiBaseUrlRequired:" in env_text
    assert "isAndroidTarget &&" in env_text
    assert "!useLocalRuntime &&" in env_text
    assert "useLocalRuntime" in env_text
    assert 'isAndroidTarget ? "/" : "/app/"' in env_text
    assert 'isAndroidTarget ? "/" : "/app"' in env_text
    assert "!isAndroidTarget" in env_text
    assert "agentTeam" in env_text
    assert "agentGovernance" in env_text
    assert "agentMemory" in env_text
    assert "observability" in env_text
    assert "productivity" in env_text

    provider_text = (web_root / "src" / "shared" / "sdk" / "focus-agent-provider.tsx").read_text()
    assert "apiBaseUrlReady" in provider_text
    assert "setApiBaseUrl" in provider_text
    assert "normalizedValue === apiBaseUrl" in provider_text
    assert "persistToken(null)" in provider_text
    assert "@/android-local-runtime/local-focus-agent-runtime" in provider_text
    assert "createLocalFocusAgentFetch" in provider_text
    assert "fetchImpl: localRuntimeFetch" in provider_text
    assert "new FocusAgentClient" in provider_text

    local_runtime_text = _android_local_runtime_text(web_root)
    local_runtime_constants_text = (
        web_root / "src" / "android-local-runtime" / "constants.ts"
    ).read_text()
    assert "createLocalFocusAgentFetch" in local_runtime_text
    assert "CapacitorHttp.post" in local_runtime_text
    assert "FocusAgentSecureStorage" in local_runtime_text
    assert "SECRET_STORAGE_KEY" in local_runtime_text
    assert "abortIfRequested(signal)" in local_runtime_text
    assert "postOpenAiCompatibleChatCompletion" in local_runtime_text
    assert "modelSecrets" in local_runtime_text
    assert "this.state.modelSecrets" in local_runtime_text
    assert "delete this.state.modelSecrets" in local_runtime_text
    assert "providerConfigForModel" in local_runtime_text
    assert "providerMatchesModelPrefix" in local_runtime_text
    assert "modelProvider(selectedModel" in local_runtime_text
    assert "delete ctx.modelSecrets[providerId]" in local_runtime_text
    assert "api_key_default" in local_runtime_text
    assert 'DEFAULT_PROVIDER_ID = "deepseek"' in local_runtime_constants_text
    assert 'DEFAULT_PROVIDER_BASE_URL = "https://api.deepseek.com"' in local_runtime_constants_text
    assert 'DEFAULT_MODEL_ID = "deepseek-v4-pro"' in local_runtime_constants_text
    assert 'Content-Type": "text/event-stream"' in local_runtime_constants_text
    assert "streamRun" in local_runtime_text
    assert 'resource === "branch-decisions"' in local_runtime_text
    assert 'resource === "branch-actions"' in local_runtime_text
    assert "item.action_id === subresource" in local_runtime_text
    assert "branchDecisionConfig" in local_runtime_text
    assert 'resource === "admin"' in local_runtime_text

    login_text = (web_root / "src" / "pages" / "auth" / "login-page.tsx").read_text()
    assert "ApiBaseUrlPanel" in login_text
    assert "apiBaseUrlReady" in login_text
    assert "authReady={ready && apiBaseUrlReady}" in login_text

    admin_config_text = (web_root / "src" / "pages" / "admin" / "admin-config-page.tsx").read_text()
    assert "appEnv.useLocalRuntime" in admin_config_text
    assert "api_key_default" in admin_config_text
    assert "showLocalSecrets={appEnv.useLocalRuntime}" in admin_config_text

    model_panel_text = (
        web_root / "src" / "pages" / "admin" / "admin-config-model-panel.tsx"
    ).read_text()
    assert "showLocalSecrets" in model_panel_text
    assert 'type="password"' in model_panel_text
    assert "本机 API Key" in model_panel_text

    login_intro_text = (web_root / "src" / "pages" / "auth" / "login-intro.tsx").read_text()
    assert "hasWorkspace" in login_intro_text
    assert "appEnv.features.agentGovernance" in login_intro_text
    assert "appEnv.features.observability" in login_intro_text
    assert "对话与管理优先的 Focus Agent" in login_intro_text

    account_portal_text = (web_root / "src" / "pages" / "auth" / "account-portal.tsx").read_text()
    assert "appEnv.features.agentTeam" in account_portal_text
    assert "appEnv.features.agentGovernance" in account_portal_text
    assert "appEnv.features.agentMemory" in account_portal_text
    assert "appEnv.features.observability" in account_portal_text
    assert "appEnv.features.productivity" in account_portal_text
    assert "enabledModules.push" in account_portal_text

    register_text = (web_root / "src" / "pages" / "auth" / "register-page.tsx").read_text()
    assert "ApiBaseUrlPanel" in register_text
    assert "apiBaseUrlReady" in register_text
    assert "!apiBaseUrlReady" in register_text

    router_text = (web_root / "src" / "app" / "router.tsx").read_text()
    assert "appEnv.features.agentTeam" in router_text
    assert "appEnv.features.agentGovernance" in router_text
    assert "appEnv.features.agentMemory" in router_text
    assert "appEnv.features.observability" in router_text
    assert "appEnv.features.productivity" in router_text
    assert "...agentTeamRoutes" in router_text
    assert "...agentGovernanceRoutes" in router_text
    assert "...agentMemoryRoutes" in router_text
    assert "...observabilityRoutes" in router_text
    assert "...productivityRoutes" in router_text
    assert "basepath: appEnv.routerBasePath" in router_text

    shell_config_text = (web_root / "src" / "app" / "shell" / "app-shell-config.ts").read_text()
    assert "if (!appEnv.features.productivity) return false" in shell_config_text
    assert "appEnv.features.agentTeam" in shell_config_text
    assert "appEnv.features.agentGovernance" in shell_config_text
    assert "appEnv.features.agentMemory" in shell_config_text
    assert "appEnv.features.observability" in shell_config_text


def test_android_feature_flags_hide_productivity_and_agent_team():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web"

    package_json = json.loads((root / "package.json").read_text())
    android_build_script = package_json["scripts"]["android:web:build"]
    assert "VITE_FOCUS_AGENT_TARGET=android" in android_build_script
    assert "VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH=false" in android_build_script
    assert "VITE_FOCUS_AGENT_ENABLE_PRODUCTIVITY=false" in android_build_script

    env_text = (web_root / "src" / "shared" / "config" / "env.ts").read_text()
    assert re.search(
        r"agentTeam:\s*envFlag\(\s*"
        r"import\.meta\.env\.VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH,\s*"
        r"!isAndroidTarget,\s*\)",
        env_text,
        re.S,
    )
    assert re.search(
        r"agentGovernance:\s*envFlag\(\s*"
        r"import\.meta\.env\.VITE_FOCUS_AGENT_ENABLE_AGENT_GOVERNANCE,\s*"
        r"true,\s*\)",
        env_text,
        re.S,
    )
    assert re.search(
        r"agentMemory:\s*envFlag\(\s*"
        r"import\.meta\.env\.VITE_FOCUS_AGENT_ENABLE_AGENT_MEMORY,\s*"
        r"true,\s*\)",
        env_text,
        re.S,
    )
    assert re.search(
        r"observability:\s*envFlag\(\s*"
        r"import\.meta\.env\.VITE_FOCUS_AGENT_ENABLE_OBSERVABILITY,\s*"
        r"true,\s*\)",
        env_text,
        re.S,
    )
    assert re.search(
        r"productivity:\s*envFlag\(\s*"
        r"import\.meta\.env\.VITE_FOCUS_AGENT_ENABLE_PRODUCTIVITY,\s*"
        r"!isAndroidTarget,\s*\)",
        env_text,
        re.S,
    )

    router_text = (web_root / "src" / "app" / "router.tsx").read_text()
    assert 'path: "/productivity/notes"' in router_text
    assert 'path: "/productivity/tasks"' in router_text
    assert "const productivityRoutes =" in router_text
    assert "const agentTeamRoutes =" in router_text
    assert 'VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH === "false"' in router_text
    assert 'VITE_FOCUS_AGENT_ENABLE_PRODUCTIVITY === "false"' in router_text
    assert "LazyAgentTeamWorkbenchPage" in router_text
    assert "LazyProductivityPage" in router_text
    assert "import { AgentTeamWorkbenchPage }" not in router_text
    assert "import { ProductivityPage }" not in router_text
    assert "const agentGovernanceRoutes = appEnv.features.agentGovernance" in router_text
    assert "const agentMemoryRoutes = appEnv.features.agentMemory" in router_text
    assert "const observabilityRoutes = appEnv.features.observability" in router_text
    assert "[productivityNotesRoute, productivityTasksRoute]" in router_text

    auth_page_data_text = (web_root / "src" / "pages" / "auth" / "auth-page-data.tsx").read_text()
    assert (
        'if (path.startsWith("/agent-team")) return appEnv.features.agentTeam'
        in auth_page_data_text
    )
    assert (
        'if (path.startsWith("/agent/memory")) return appEnv.features.agentMemory'
        in auth_page_data_text
    )
    assert (
        'if (path.startsWith("/agent/")) return appEnv.features.agentGovernance'
        in auth_page_data_text
    )
    assert (
        'if (path.startsWith("/observability/")) return appEnv.features.observability'
        in auth_page_data_text
    )
    assert (
        'if (path.startsWith("/productivity/")) return appEnv.features.productivity'
        in auth_page_data_text
    )

    shell_navigation_text = (
        web_root / "src" / "app" / "shell" / "app-shell-global-navigation.tsx"
    ).read_text()
    assert "{appEnv.features.productivity ? (" in shell_navigation_text
    assert 'to="/productivity/tasks"' in shell_navigation_text

    shell_route_state_text = (
        web_root / "src" / "app" / "shell" / "hooks" / "use-shell-route-state.ts"
    ).read_text()
    assert "appEnv.features.agentTeam &&" in shell_route_state_text
    assert 'routeState.pathname === "/agent-team"' in shell_route_state_text


def test_android_local_runtime_supports_focus_score_branch_recommendations_and_web_search():
    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web"

    local_runtime_text = _android_local_runtime_text(web_root)
    local_tool_execution_text = (
        web_root / "src" / "android-local-runtime" / "local-tool-execution.ts"
    ).read_text()
    android_smoke_text = (web_root / "scripts" / "android-local-runtime-smoke.mjs").read_text()
    assert "recordLocalBranchDecision" in local_runtime_text
    assert "branch_decision_summary" in local_runtime_text
    assert "semantic_relatedness" in local_runtime_text
    assert "FocusAgentBranchDecisionSummary" in local_runtime_text
    assert 'source: "branch_decision"' in local_runtime_text
    assert "recommendation_user_visible: true" in local_runtime_text
    assert 'event: "tool.requested"' in local_runtime_text
    assert 'event: "tool.result"' in local_runtime_text
    assert 'event: "tool.error"' in local_runtime_text
    assert "runLocalWebSearch" in local_runtime_text
    assert "runLocalWebFetch" in local_runtime_text
    assert "searchQueryCore" in local_runtime_text
    assert "requiresTemporalAnchor" in local_runtime_text
    assert "relativeDateParts" in local_runtime_text
    assert "searchLocationScope" in local_runtime_text
    assert "webSearchQuery(" in local_runtime_text
    assert "currentUtcTimeResult" in local_runtime_text
    assert "localRoleDecision" in local_runtime_text
    assert "localSkillCatalogItems" in local_runtime_text
    assert "localSelectedSkills" in local_runtime_text
    assert "localContextEvidenceRecord" in local_runtime_text
    assert "prompt_chars" in local_runtime_text
    assert "compression_plan" in local_runtime_text
    assert 'source_kind: "context_explain"' in local_runtime_text
    assert "parseDuckDuckGoHtmlResults" in local_runtime_text
    assert "https://duckduckgo.com/${endpoint}" in local_runtime_text
    assert "duckduckgo_lite" in local_runtime_text
    assert "executeLocalAppTool" in local_runtime_text
    assert "localAppToolPlan" in local_runtime_text
    assert "ANDROID_LOCAL_SKILLS" in local_runtime_text
    assert "defaultWorkspaceFiles" in local_runtime_text
    assert "applyPatchToWorkspace" in local_runtime_text
    assert "workspaceDiff" in local_runtime_text
    assert "api.duckduckgo.com" in local_runtime_text
    assert "write_text_artifact" in local_runtime_text
    assert "artifact_list" in local_runtime_text
    assert "memory_search" in local_runtime_text
    assert "conversation_summary" in local_runtime_text
    assert "skills_search" in local_runtime_text
    assert (
        "thread.active_skill_ids = [...thread.active_skill_ids, skill.skill_id]"
        in local_tool_execution_text
    )
    assert ") ?? ANDROID_LOCAL_SKILLS[0]" not in local_tool_execution_text
    assert "web_fetch" in local_runtime_text
    assert "web_search" in local_runtime_text
    assert "current_utc_time" in local_runtime_text
    assert "handleAgent" in local_runtime_text
    assert "handleMemory" in local_runtime_text
    assert "handleObservability" in local_runtime_text
    assert "localCapabilities" in local_runtime_text
    assert "localObservabilityOverview" in local_runtime_text
    assert 'resource === "agent"' in local_runtime_text
    assert 'resource === "memory"' in local_runtime_text
    assert 'resource === "observability"' in local_runtime_text
    assert "Productivity is disabled in the Android local runtime." in local_runtime_text
    assert "appEnv.features.agentTeam, false" in android_smoke_text
    assert "appEnv.features.agentGovernance, true" in android_smoke_text
    assert "appEnv.features.agentMemory, true" in android_smoke_text
    assert "appEnv.features.observability, true" in android_smoke_text
    assert "appEnv.features.productivity, false" in android_smoke_text
    assert "FocusAgentClient" in android_smoke_text
    assert "LocalFocusAgentRuntime" in android_smoke_text
    assert "assertAdminConfigContract" in android_smoke_text
    assert "assertModelsResponseContract" in android_smoke_text
    assert "assertLocalRuntimeExposeContract" in android_smoke_text
    assert "assertLocalStreamContract" in android_smoke_text
    assert "assertSdkStreamStateContract" in android_smoke_text
    assert "sdkClient.getPrincipal()" in android_smoke_text
    assert "sdkClient.listAgentCapabilities()" in android_smoke_text
    assert "sdkClient.updateAdminModelConfig" in android_smoke_text
    assert "sdkClient.updateAdminToolConfig" in android_smoke_text
    assert "sdkClient.updateAdminPolicyConfig" in android_smoke_text
    assert "sdkClient.routeAgentTools" in android_smoke_text
    assert "sdkClient.forkBranch" in android_smoke_text
    assert "sdkClient.promoteBranchDecision" in android_smoke_text
    assert "sdkClient.dismissBranchAction" in android_smoke_text
    assert "sdkClient.forgetMemoryRecord" in android_smoke_text
    assert "sdkClient.listTrajectoryTurns" in android_smoke_text
    assert "sdkClient.streamResume" in android_smoke_text
    assert "sdkClient.cancelHarnessRun" in android_smoke_text
    assert "sdkClient.streamTurn" in android_smoke_text
    assert "sdkClient.collectStream" in android_smoke_text
    assert 'sdkFallbackState.visibleText.includes("还没有配置模型 API Key")' in android_smoke_text
    assert "providerRequests.length" in android_smoke_text
    assert 'terminal.event,\n\t\t"run.completed"' in android_smoke_text
    assert "threadState.assistant_message" in android_smoke_text
    assert "messageRecord.id" in android_smoke_text
    assert "/v1/agent/capabilities" in android_smoke_text
    assert 'adminToolNames.includes("write_text_artifact")' in android_smoke_text
    assert 'adminToolNames.includes("memory_search")' in android_smoke_text
    assert 'event.data.tool_name === "write_text_artifact"' in android_smoke_text
    assert 'event.data.tool_name === "memory_save"' in android_smoke_text
    assert 'event.data.tool_name === "artifact_list"' in android_smoke_text
    assert 'event.data.tool_name === "conversation_summary"' in android_smoke_text
    assert 'event.data.tool_name === "skills_search"' in android_smoke_text
    assert 'event.data.tool_name === "skill_install"' in android_smoke_text
    assert 'event.data.tool_name === "skills_refresh_index"' in android_smoke_text
    assert 'event.data.tool_name === "list_files"' in android_smoke_text
    assert 'event.data.tool_name === "apply_patch"' in android_smoke_text
    assert 'event.data.tool_name === "git_diff"' in android_smoke_text
    assert 'event.data.tool_name === "run_workspace_command"' in android_smoke_text
    assert 'model: "kimi:kimi-k2.6"' in android_smoke_text
    assert 'providerRequests[0].body.model, "kimi-k2.6"' in android_smoke_text
    assert 'providerRequests[0].authorization, "Bearer moonshot-key"' in android_smoke_text
    assert "moonshotProviderWithoutSecret" in android_smoke_text
    assert "api_key_configured" in android_smoke_text
    assert 'tool.name === "web_fetch"' in android_smoke_text
    assert "/v1/memory" in android_smoke_text
    assert "/v1/observability/overview" in android_smoke_text
    assert "/v1/observability/trajectory" in android_smoke_text
    assert "expectStatus" in android_smoke_text
    assert "/v1/notes" in android_smoke_text
    assert "/v1/tasks" in android_smoke_text
    assert "/v1/productivity/capture/note" in android_smoke_text
    assert 'event.data.tool_name === "web_fetch"' in android_smoke_text
    assert 'event.event === "tool.requested"' in android_smoke_text
    assert 'event.data.tool_name === "web_search"' in android_smoke_text
    assert 'searchRequest?.data.args?.query.includes("原始查询：")' in android_smoke_text
    assert 'searchRequest?.data.args?.query.includes("当前UTC时间：")' in android_smoke_text
    assert 'searchRequest?.data.args?.query.includes("请联网查一下")' in android_smoke_text
    assert 'event.data.output?.source === "duckduckgo_html"' in android_smoke_text
    assert '"https://duckduckgo.com/html/"' in android_smoke_text
    assert "roleDryRun.plan.decisions[0].model_id" in android_smoke_text
    assert 'skill.skill_id === "android-local-runtime"' in android_smoke_text
    assert 'skillSelection.skill_ids.includes("local-web-tools")' in android_smoke_text
    assert "contextPreview.decision.budget.prompt_chars" in android_smoke_text
    assert 'contextEvidence.backend, "android-local"' in android_smoke_text
    assert "contextExplain.item.evidence_id" in android_smoke_text
    assert "taskLedgerPreview.ledger.tasks.length" in android_smoke_text
    assert "toolRoute.plan.decisions.map" in android_smoke_text
    assert 'completed?.data.branch_decision?.status, "promoted"' in android_smoke_text
    assert 'executed.branch_action.status, "executed"' in android_smoke_text

    provider_text = (web_root / "src" / "shared" / "sdk" / "focus-agent-provider.tsx").read_text()
    assert "@/android-local-runtime/local-focus-agent-runtime" in provider_text
    assert "createLocalFocusAgentFetch()" in provider_text
