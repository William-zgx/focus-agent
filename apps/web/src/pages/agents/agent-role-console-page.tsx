import {
  type FocusAgentCapabilityListResponse,
  type FocusAgentContextArtifactListResponse,
  type FocusAgentContextDecisionListResponse,
  type FocusAgentContextPolicyResponse,
  type FocusAgentContextPreviewResponse,
  type FocusAgentDelegationPolicyResponse,
  type FocusAgentDelegationRunListResponse,
  type FocusAgentMemoryCuratorDecisionListResponse,
  type FocusAgentMemoryCuratorPolicyResponse,
  type FocusAgentModelRouterDecisionListResponse,
  type FocusAgentModelRouterPolicyResponse,
  type FocusAgentReviewQueueListResponse,
  type FocusAgentRoleDecisionListResponse,
  type FocusAgentRoleDryRunResponse,
  type FocusAgentRolePolicyResponse,
  type FocusAgentSelfRepairFailureListResponse,
  type FocusAgentToolRouteDecisionListResponse,
  type FocusAgentToolRouteResponse,
} from "@focus-agent/web-sdk";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

const DEFAULT_DRY_RUN_MESSAGE =
  "Plan the implementation, update backend and Web code, verify regression gates, and prepare release notes.";

function roleLabel(role: string) {
  return role.replaceAll("_", " ");
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function jsonPreview(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function useAgentRolePolicy() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentRolePolicyResponse>({
    queryKey: queryKeys.agentRolePolicy,
    queryFn: () => client.getAgentRolePolicy(),
    enabled: ready,
  });
}

function useAgentRoleDecisions() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentRoleDecisionListResponse>({
    queryKey: queryKeys.agentRoleDecisions(50),
    queryFn: () => client.listAgentRoleDecisions(50),
    enabled: ready,
  });
}

function useAgentCapabilities() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentCapabilityListResponse>({
    queryKey: queryKeys.agentCapabilities,
    queryFn: () => client.listAgentCapabilities(),
    enabled: ready,
  });
}

function useAgentToolRouteDecisions() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentToolRouteDecisionListResponse>({
    queryKey: queryKeys.agentToolRouteDecisions(50),
    queryFn: () => client.listAgentToolRouteDecisions(50),
    enabled: ready,
  });
}

function useAgentMemoryCuratorPolicy() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentMemoryCuratorPolicyResponse>({
    queryKey: queryKeys.agentMemoryCuratorPolicy,
    queryFn: () => client.getAgentMemoryCuratorPolicy(),
    enabled: ready,
  });
}

function useAgentMemoryCuratorDecisions() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentMemoryCuratorDecisionListResponse>({
    queryKey: queryKeys.agentMemoryCuratorDecisions(50),
    queryFn: () => client.listAgentMemoryCuratorDecisions(50),
    enabled: ready,
  });
}

function useAgentDelegationPolicy() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentDelegationPolicyResponse>({
    queryKey: queryKeys.agentDelegationPolicy,
    queryFn: () => client.getAgentDelegationPolicy(),
    enabled: ready,
  });
}

function useAgentDelegationRuns() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentDelegationRunListResponse>({
    queryKey: queryKeys.agentDelegationRuns(50),
    queryFn: () => client.listAgentDelegationRuns(50),
    enabled: ready,
  });
}

function useAgentModelRouterPolicy() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentModelRouterPolicyResponse>({
    queryKey: queryKeys.agentModelRouterPolicy,
    queryFn: () => client.getAgentModelRouterPolicy(),
    enabled: ready,
  });
}

function useAgentModelRouterDecisions() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentModelRouterDecisionListResponse>({
    queryKey: queryKeys.agentModelRouterDecisions(50),
    queryFn: () => client.listAgentModelRouterDecisions(50),
    enabled: ready,
  });
}

function useAgentSelfRepairFailures() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentSelfRepairFailureListResponse>({
    queryKey: queryKeys.agentSelfRepairFailures(50),
    queryFn: () => client.listAgentSelfRepairFailures(50),
    enabled: ready,
  });
}

function useAgentReviewQueue() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentReviewQueueListResponse>({
    queryKey: queryKeys.agentReviewQueue(50),
    queryFn: () => client.listAgentReviewQueue(50),
    enabled: ready,
  });
}

function useAgentContextPolicy() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentContextPolicyResponse>({
    queryKey: queryKeys.agentContextPolicy,
    queryFn: () => client.getAgentContextPolicy(),
    enabled: ready,
  });
}

function useAgentContextDecisions() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentContextDecisionListResponse>({
    queryKey: queryKeys.agentContextDecisions(50),
    queryFn: () => client.listAgentContextDecisions(50),
    enabled: ready,
  });
}

function useAgentContextArtifacts() {
  const { client, ready } = useFocusAgent();
  return useQuery<FocusAgentContextArtifactListResponse>({
    queryKey: queryKeys.agentContextArtifacts(50),
    queryFn: () => client.listAgentContextArtifacts(50),
    enabled: ready,
  });
}

export function AgentRoleConsolePage() {
  const { client } = useFocusAgent();
  const { isChineseUi } = useShellUi();
  const [message, setMessage] = useState(DEFAULT_DRY_RUN_MESSAGE);
  const [availableTools, setAvailableTools] = useState(
    "search_code,read_file,git_diff,web_search,memory_search,skills_list,skill_view,write_text_artifact",
  );
  const policy = useAgentRolePolicy();
  const decisions = useAgentRoleDecisions();
  const capabilities = useAgentCapabilities();
  const toolRouteDecisions = useAgentToolRouteDecisions();
  const memoryPolicy = useAgentMemoryCuratorPolicy();
  const memoryDecisions = useAgentMemoryCuratorDecisions();
  const delegationPolicy = useAgentDelegationPolicy();
  const delegationRuns = useAgentDelegationRuns();
  const modelRouterPolicy = useAgentModelRouterPolicy();
  const modelRouterDecisions = useAgentModelRouterDecisions();
  const selfRepairFailures = useAgentSelfRepairFailures();
  const reviewQueue = useAgentReviewQueue();
  const contextPolicy = useAgentContextPolicy();
  const contextDecisions = useAgentContextDecisions();
  const contextArtifacts = useAgentContextArtifacts();
  const [toolRouteRole, setToolRouteRole] = useState("executor");
  const [toolRoutePolicy, setToolRoutePolicy] = useState("execution");
  const dryRun = useMutation<FocusAgentRoleDryRunResponse, Error>({
    mutationFn: () =>
      client.dryRunAgentRoleRoute({
        message,
        scene: "role_routing_console",
        available_tools: availableTools
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      }),
  });
  const toolRoute = useMutation<FocusAgentToolRouteResponse, Error>({
    mutationFn: () =>
      client.routeAgentTools({
        role: toolRouteRole,
        tool_policy: toolRoutePolicy,
        available_tools: availableTools
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      }),
  });
  const contextPreview = useMutation<FocusAgentContextPreviewResponse, Error>({
    mutationFn: () =>
      client.previewAgentContext({
        prompt_mode: "execute",
        role: "executor",
        assembled_context: `${message}\n\n${availableTools.repeat(80)}`,
        state: {
          context_budget: {
            prompt_token_limit: 1200,
            chars_per_token: 1,
          },
          rolling_summary: message.repeat(20),
        },
      }),
  });
  const dryRunPlan = asRecord(dryRun.data?.plan);
  const dryRunDecisions = asArray(dryRunPlan.decisions);
  const toolRoutePlan = asRecord(toolRoute.data?.plan);
  const toolRoutePlanDecisions = asArray(toolRoutePlan.decisions);
  const roleModels = useMemo(
    () => Object.entries(policy.data?.role_models ?? {}),
    [policy.data?.role_models],
  );
  const recentDecisionItems = decisions.data?.items ?? [];
  const capabilityItems = capabilities.data?.items ?? [];
  const recentToolRouteItems = toolRouteDecisions.data?.items ?? [];
  const recentMemoryItems = memoryDecisions.data?.items ?? [];
  const recentDelegationRuns = delegationRuns.data?.items ?? [];
  const recentModelRouteItems = modelRouterDecisions.data?.items ?? [];
  const recentFailures = selfRepairFailures.data?.items ?? [];
  const reviewQueueItems = reviewQueue.data?.items ?? [];
  const recentContextDecisions = contextDecisions.data?.items ?? [];
  const recentContextArtifacts = contextArtifacts.data?.items ?? [];
  const contextPreviewDecision = asRecord(contextPreview.data?.decision);
  const contextPreviewBudget = asRecord(contextPreviewDecision.budget);
  const contextPreviewPlan = asRecord(contextPreviewDecision.compression_plan);

  return (
    <div className="fa-observability-layout fa-agent-role-console">
      <section className="fa-observability-hero fa-agent-role-hero">
        <div className="fa-observability-hero-copy">
          <p className="fa-observability-kicker">
            {isChineseUi ? "Agent 决策架构" : "Agent Decision Architecture"}
          </p>
          <h1>{isChineseUi ? "Agent 治理控制台" : "Agent Governance Console"}</h1>
          <p className="fa-observability-hero-text">
            {isChineseUi
              ? "查看角色路由、Memory Curator 分支语义保护，以及 Skill Scout / Tool Router 的能力注册表与实际决策。"
              : "Inspect role routing, Memory Curator branch semantics, and Skill Scout / Tool Router capability decisions."}
          </p>
          <nav
            aria-label={isChineseUi ? "诊断页面" : "Diagnostics views"}
            className="fa-trajectory-workbench-tabs fa-observability-route-tabs"
          >
            <Link className="fa-trajectory-workbench-tab fa-observability-route-tab" to="/observability/overview">
              <span>{isChineseUi ? "全局诊断" : "Global health"}</span>
              <strong>{isChineseUi ? "趋势 / 热点" : "Trends / hotspots"}</strong>
            </Link>
            <Link className="fa-trajectory-workbench-tab fa-observability-route-tab" to="/observability/trajectory">
              <span>{isChineseUi ? "单条复盘" : "Single-turn review"}</span>
              <strong>{isChineseUi ? "样本 / 证据" : "Samples / evidence"}</strong>
            </Link>
            <Link className="fa-trajectory-workbench-tab fa-observability-route-tab is-active" to="/agent/governance">
              <span>{isChineseUi ? "Agent 治理" : "Agent governance"}</span>
              <strong>{isChineseUi ? "记忆 / 工具 / 路由" : "Memory / tools / routing"}</strong>
            </Link>
          </nav>
        </div>
        <div className="fa-observability-hero-grid fa-agent-role-policy-grid">
          <div className="fa-observability-stat-card">
            <span>{isChineseUi ? "状态" : "Status"}</span>
            <strong>{policy.data?.enabled ? "enabled" : "dry-run off"}</strong>
            <p>{isChineseUi ? "角色路由仍可独立预演" : "Role routing can still be previewed"}</p>
          </div>
          <div className="fa-observability-stat-card">
            <span>{isChineseUi ? "Memory Curator" : "Memory Curator"}</span>
            <strong>{memoryPolicy.data?.enabled ? "enabled" : "disabled"}</strong>
            <p>{memoryPolicy.data?.auto_promote_on_merge ? "auto promote on merge" : "review only"}</p>
          </div>
          <div className="fa-observability-stat-card">
            <span>{isChineseUi ? "Capabilities" : "Capabilities"}</span>
            <strong>{capabilities.data?.count ?? "-"}</strong>
            <p>{isChineseUi ? "工具按角色、风险和能力注册" : "Tools are registered by role, risk, and capability"}</p>
          </div>
          <div className="fa-observability-stat-card">
            <span>{isChineseUi ? "Delegation" : "Delegation"}</span>
            <strong>{delegationPolicy.data?.enabled ? "enabled" : "disabled"}</strong>
            <p>{delegationPolicy.data?.enforce ? "enforce" : "observe"}</p>
          </div>
          <div className="fa-observability-stat-card">
            <span>{isChineseUi ? "Context v2" : "Context v2"}</span>
            <strong>{contextPolicy.data?.enabled ? "enabled" : "disabled"}</strong>
            <p>{contextPolicy.data?.artifactize_long_observations ? "artifact refs on" : "preview safe"}</p>
          </div>
        </div>
      </section>

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Policy" : "Policy"}</strong>
              <h2>{isChineseUi ? "角色模型映射" : "Role Model Mapping"}</h2>
            </div>
            <span>{policy.isLoading ? "loading" : `${roleModels.length} roles`}</span>
          </div>
          {policy.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(policy.error, "Failed to load role policy")}
            </div>
          ) : null}
          <div className="fa-agent-role-model-list">
            {roleModels.map(([role, model]) => (
              <div className="fa-agent-role-model-row" key={role}>
                <span>{roleLabel(role)}</span>
                <strong>{model ?? "-"}</strong>
              </div>
            ))}
          </div>
          <details className="fa-observability-raw-toggle">
            <summary>{isChineseUi ? "查看完整 policy JSON" : "View full policy JSON"}</summary>
            <pre>{jsonPreview(policy.data ?? {})}</pre>
          </details>
        </div>

        <div className="fa-observability-detail-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Dry run" : "Dry run"}</strong>
              <h2>{isChineseUi ? "路由预演" : "Routing Preview"}</h2>
            </div>
            <span>{dryRun.isPending ? "running" : "preview only"}</span>
          </div>
          <div className="fa-agent-role-dry-run-form">
            <label className="fa-observability-filter fa-agent-role-field">
              <span>{isChineseUi ? "任务文本" : "Task text"}</span>
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={5}
              />
            </label>
            <label className="fa-observability-filter fa-agent-role-field">
              <span>{isChineseUi ? "可用工具" : "Available tools"}</span>
              <input
                value={availableTools}
                onChange={(event) => setAvailableTools(event.target.value)}
              />
            </label>
            <div className="fa-observability-command-bar">
              <button
                className="fa-observability-preset is-primary"
                disabled={dryRun.isPending || !message.trim()}
                onClick={() => dryRun.mutate()}
                type="button"
              >
                {dryRun.isPending
                  ? isChineseUi
                    ? "预演中..."
                    : "Running..."
                  : isChineseUi
                    ? "预演路由"
                    : "Dry Run Route"}
              </button>
            </div>
          </div>
          {dryRun.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(dryRun.error, "Dry-run request failed")}
            </div>
          ) : null}
          {dryRun.data ? (
            <div className="fa-agent-role-decision-list">
              {dryRunDecisions.map((decision, index) => (
                <div className="fa-agent-role-decision-card" key={`${decision.role}-${index}`}>
                  <div>
                    <span>{roleLabel(String(decision.role ?? "role"))}</span>
                    <strong>{String(decision.model_id ?? "-")}</strong>
                  </div>
                  <p>{String(decision.rationale ?? "")}</p>
                  <pre>{jsonPreview(decision.tool_governance ?? {})}</pre>
                </div>
              ))}
            </div>
          ) : (
            <div className="fa-observability-empty is-compact">
              {isChineseUi ? "提交一次 dry-run 后，这里会展示路由决策。" : "Run a dry-run to inspect routing decisions here."}
            </div>
          )}
        </div>
      </section>

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Memory Curator" : "Memory Curator"}</strong>
              <h2>{isChineseUi ? "分支语义保护" : "Branch Semantic Guard"}</h2>
            </div>
            <span>{memoryPolicy.isLoading ? "loading" : memoryPolicy.data?.conflict_strategy ?? "needs_review"}</span>
          </div>
          {memoryPolicy.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(memoryPolicy.error, "Failed to load memory curator policy")}
            </div>
          ) : null}
          <div className="fa-agent-role-model-list">
            <div className="fa-agent-role-model-row">
              <span>{isChineseUi ? "启用状态" : "Enabled"}</span>
              <strong>{String(memoryPolicy.data?.enabled ?? false)}</strong>
            </div>
            <div className="fa-agent-role-model-row">
              <span>{isChineseUi ? "合并自动提升" : "Auto promote on merge"}</span>
              <strong>{String(memoryPolicy.data?.auto_promote_on_merge ?? true)}</strong>
            </div>
            <div className="fa-agent-role-model-row">
              <span>{isChineseUi ? "冲突策略" : "Conflict strategy"}</span>
              <strong>{memoryPolicy.data?.conflict_strategy ?? "needs_review"}</strong>
            </div>
          </div>
          <div className="fa-agent-role-trajectory-list">
            {recentMemoryItems.slice(0, 5).map((item, index) => (
              <details className="fa-agent-role-trajectory-row" key={`memory-${index}`}>
                <summary>
                  <span>{String(item.branch_id ?? item.turn_id ?? "memory")}</span>
                  <strong>{String(item.status ?? "curator decision")}</strong>
                </summary>
                <pre>{jsonPreview(item)}</pre>
              </details>
            ))}
            {!recentMemoryItems.length ? (
              <div className="fa-observability-empty is-compact">
                {isChineseUi ? "还没有 memory curator trajectory 记录。" : "No memory curator trajectory records yet."}
              </div>
            ) : null}
          </div>
        </div>

        <div className="fa-observability-detail-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Tool Router" : "Tool Router"}</strong>
              <h2>{isChineseUi ? "能力路由预演" : "Capability Routing"}</h2>
            </div>
            <span>{toolRoute.isPending ? "routing" : "enforced plan"}</span>
          </div>
          <div className="fa-agent-role-dry-run-form">
            <label className="fa-observability-filter fa-agent-role-field">
              <span>{isChineseUi ? "角色" : "Role"}</span>
              <select value={toolRouteRole} onChange={(event) => setToolRouteRole(event.target.value)}>
                <option value="executor">executor</option>
                <option value="critic">critic</option>
                <option value="planner">planner</option>
                <option value="memory_curator">memory_curator</option>
                <option value="skill_scout">skill_scout</option>
              </select>
            </label>
            <label className="fa-observability-filter fa-agent-role-field">
              <span>{isChineseUi ? "工具策略" : "Tool policy"}</span>
              <select value={toolRoutePolicy} onChange={(event) => setToolRoutePolicy(event.target.value)}>
                <option value="execution">execution</option>
                <option value="workspace_lookup">workspace_lookup</option>
                <option value="live_web_research">live_web_research</option>
                <option value="direct_answer">direct_answer</option>
              </select>
            </label>
            <div className="fa-observability-command-bar">
              <button
                className="fa-observability-preset is-primary"
                disabled={toolRoute.isPending}
                onClick={() => toolRoute.mutate()}
                type="button"
              >
                {toolRoute.isPending ? (isChineseUi ? "路由中..." : "Routing...") : isChineseUi ? "预演工具路由" : "Route Tools"}
              </button>
            </div>
          </div>
          {toolRoute.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(toolRoute.error, "Tool route request failed")}
            </div>
          ) : null}
          {toolRoute.data ? (
            <div className="fa-agent-role-decision-list">
              {toolRoutePlanDecisions.map((decision, index) => (
                <div className="fa-agent-role-decision-card" key={`route-${decision.name}-${index}`}>
                  <div>
                    <span>{String(decision.name ?? "tool")}</span>
                    <strong>{String(decision.allowed ?? false)}</strong>
                  </div>
                  <p>{String(decision.reason ?? "")}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="fa-observability-empty is-compact">
              {isChineseUi ? "运行一次工具路由后，这里会展示 allow/deny 决策。" : "Run tool routing to inspect allow/deny decisions."}
            </div>
          )}
        </div>
      </section>

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Delegation Runs" : "Delegation Runs"}</strong>
              <h2>{isChineseUi ? "多 Agent 执行轨迹" : "Multi-Agent Execution"}</h2>
            </div>
            <span>{delegationRuns.data?.trajectory_available ? `${recentDelegationRuns.length} runs` : "not available"}</span>
          </div>
          <div className="fa-agent-role-trajectory-list">
            {recentDelegationRuns.slice(0, 6).map((item, index) => (
              <details className="fa-agent-role-trajectory-row" key={`delegation-${index}`}>
                <summary>
                  <span>{String(item.role ?? item.task_id ?? "role")}</span>
                  <strong>{String(item.status ?? "planned")}</strong>
                </summary>
                <pre>{jsonPreview(item)}</pre>
              </details>
            ))}
            {!recentDelegationRuns.length ? (
              <div className="fa-observability-empty is-compact">
                {isChineseUi ? "还没有 agent_delegation_plan 记录。" : "No agent_delegation_plan records yet."}
              </div>
            ) : null}
          </div>
        </div>

        <div className="fa-observability-detail-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Model Router" : "Model Router"}</strong>
              <h2>{isChineseUi ? "成本 / 质量 / 延迟路由" : "Cost / Quality / Latency"}</h2>
            </div>
            <span>{modelRouterPolicy.data?.enabled ? modelRouterPolicy.data.mode : "disabled"}</span>
          </div>
          <div className="fa-agent-role-model-list">
            {Object.entries(modelRouterPolicy.data?.role_models ?? {}).map(([role, model]) => (
              <div className="fa-agent-role-model-row" key={`model-router-${role}`}>
                <span>{roleLabel(role)}</span>
                <strong>{model ?? "-"}</strong>
              </div>
            ))}
          </div>
          <div className="fa-agent-role-trajectory-list">
            {recentModelRouteItems.slice(0, 4).map((item, index) => (
              <details className="fa-agent-role-trajectory-row" key={`model-route-${index}`}>
                <summary>
                  <span>{String(item.role ?? "executor")}</span>
                  <strong>{String(item.effective_model ?? item.recommended_model ?? "-")}</strong>
                </summary>
                <pre>{jsonPreview(item)}</pre>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Self Repair" : "Self Repair"}</strong>
              <h2>{isChineseUi ? "失败归因与候选样本" : "Failure Triage"}</h2>
            </div>
            <span>{selfRepairFailures.data?.trajectory_available ? `${recentFailures.length} failures` : "not available"}</span>
          </div>
          {recentFailures.slice(0, 5).map((item, index) => (
            <details className="fa-agent-role-trajectory-row" key={`failure-${index}`}>
              <summary>
                <span>{String(item.failure_type ?? "failure")}</span>
                <strong>{String(item.failed_role ?? "role")}</strong>
              </summary>
              <pre>{jsonPreview(item)}</pre>
            </details>
          ))}
          {!recentFailures.length ? (
            <div className="fa-observability-empty is-compact">
              {isChineseUi ? "还没有 agent failure 记录。" : "No agent failure records yet."}
            </div>
          ) : null}
        </div>

        <div className="fa-observability-detail-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Review Queue" : "Review Queue"}</strong>
              <h2>{isChineseUi ? "人工干预队列" : "Human Review Queue"}</h2>
            </div>
            <span>{reviewQueue.data?.trajectory_available ? `${reviewQueueItems.length} items` : "not available"}</span>
          </div>
          {reviewQueueItems.slice(0, 5).map((item, index) => (
            <details className="fa-agent-role-trajectory-row" key={`review-${index}`}>
              <summary>
                <span>{String(item.item_type ?? "review")}</span>
                <strong>{String(item.status ?? "pending")}</strong>
              </summary>
              <pre>{jsonPreview(item)}</pre>
            </details>
          ))}
          {!reviewQueueItems.length ? (
            <div className="fa-observability-empty is-compact">
              {isChineseUi ? "还没有待人工确认的治理项。" : "No pending governance review items."}
            </div>
          ) : null}
        </div>
      </section>

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Context Engineering v2" : "Context Engineering v2"}</strong>
              <h2>{isChineseUi ? "长上下文压缩策略" : "Long Context Policy"}</h2>
            </div>
            <span>{contextPolicy.data?.enabled ? "enabled" : "disabled"}</span>
          </div>
          {contextPolicy.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(contextPolicy.error, "Failed to load context policy")}
            </div>
          ) : null}
          <div className="fa-agent-role-model-list">
            <div className="fa-agent-role-model-row">
              <span>{isChineseUi ? "Tokenizer" : "Tokenizer"}</span>
              <strong>{contextPolicy.data?.tokenizer_mode ?? "chars_fallback"}</strong>
            </div>
            <div className="fa-agent-role-model-row">
              <span>{isChineseUi ? "Artifact 阈值" : "Artifact threshold"}</span>
              <strong>{contextPolicy.data?.artifact_min_chars ?? 12000}</strong>
            </div>
            <div className="fa-agent-role-model-row">
              <span>{isChineseUi ? "角色视图" : "Role views"}</span>
              <strong>{String(contextPolicy.data?.role_views_enabled ?? false)}</strong>
            </div>
          </div>
          <div className="fa-observability-command-bar">
            <button
              className="fa-observability-preset is-primary"
              disabled={contextPreview.isPending}
              onClick={() => contextPreview.mutate()}
              type="button"
            >
              {contextPreview.isPending
                ? isChineseUi
                  ? "预览中..."
                  : "Previewing..."
                : isChineseUi
                  ? "预览压缩决策"
                  : "Preview Context"}
            </button>
          </div>
          {contextPreview.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(contextPreview.error, "Context preview request failed")}
            </div>
          ) : null}
          {contextPreview.data ? (
            <div className="fa-agent-role-model-list">
              <div className="fa-agent-role-model-row">
                <span>{isChineseUi ? "Prompt chars" : "Prompt chars"}</span>
                <strong>{String(contextPreviewBudget.prompt_chars ?? 0)}</strong>
              </div>
              <div className="fa-agent-role-model-row">
                <span>{isChineseUi ? "Over budget" : "Over budget"}</span>
                <strong>{String(contextPreviewBudget.over_budget_chars ?? 0)}</strong>
              </div>
              <div className="fa-agent-role-model-row">
                <span>{isChineseUi ? "Saved chars" : "Saved chars"}</span>
                <strong>{String(contextPreviewPlan.estimated_saved_chars ?? 0)}</strong>
              </div>
            </div>
          ) : (
            <div className="fa-observability-empty is-compact">
              {isChineseUi ? "运行一次预览后，这里会展示预算和压缩结果。" : "Run a preview to inspect budget and compression output."}
            </div>
          )}
        </div>

        <div className="fa-observability-detail-panel fa-agent-role-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Context Artifacts" : "Context Artifacts"}</strong>
              <h2>{isChineseUi ? "Artifact 化证据" : "Artifactized Evidence"}</h2>
            </div>
            <span>{contextArtifacts.data?.trajectory_available ? `${recentContextArtifacts.length} refs` : "not available"}</span>
          </div>
          {recentContextArtifacts.slice(0, 5).map((item, index) => (
            <details className="fa-agent-role-trajectory-row" key={`context-artifact-${index}`}>
              <summary>
                <span>{String(item.title ?? item.artifact_id ?? "artifact")}</span>
                <strong>{String(item.source ?? "context")}</strong>
              </summary>
              <pre>{jsonPreview(item)}</pre>
            </details>
          ))}
          {!recentContextArtifacts.length ? (
            <div className="fa-observability-empty is-compact">
              {isChineseUi ? "还没有 context artifact trajectory 记录。" : "No context artifact trajectory records yet."}
            </div>
          ) : null}
        </div>
      </section>

      <section className="fa-observability-detail-block fa-agent-role-trajectory">
        <div className="fa-observability-panel-header">
          <div>
            <strong>{isChineseUi ? "Capability Registry" : "Capability Registry"}</strong>
            <h2>{isChineseUi ? "工具能力注册表" : "Tool Capability Registry"}</h2>
          </div>
          <span>{capabilities.isLoading ? "loading" : `${capabilityItems.length} tools`}</span>
        </div>
        {capabilities.error ? (
          <div className="fa-inline-notice is-danger">
            {errorMessage(capabilities.error, "Failed to load capabilities")}
          </div>
        ) : null}
        <div className="fa-agent-role-model-list">
          {capabilityItems.map((item) => (
            <div className="fa-agent-role-model-row" key={item.name}>
              <span>{item.name}</span>
              <strong>{`${item.toolset ?? "core"} / ${item.risk_level}`}</strong>
              <small>{item.allowed_roles.join(", ") || "no roles"}</small>
            </div>
          ))}
          {!capabilityItems.length ? (
            <div className="fa-observability-empty is-compact">
              {isChineseUi ? "当前没有可展示的工具能力。" : "No tool capabilities to display."}
            </div>
          ) : null}
        </div>
      </section>

      <section className="fa-observability-detail-block fa-agent-role-trajectory">
        <div className="fa-observability-panel-header">
          <div>
            <strong>{isChineseUi ? "Context Decisions" : "Context Decisions"}</strong>
            <h2>{isChineseUi ? "最近上下文预算记录" : "Recent Context Budget Records"}</h2>
          </div>
          <span>{contextDecisions.data?.trajectory_available ? `${contextDecisions.data.count} records` : "not available"}</span>
        </div>
        {recentContextDecisions.slice(0, 8).map((item, index) => (
          <details className="fa-agent-role-trajectory-row" key={`context-decision-${index}`}>
            <summary>
              <span>{String(item.turn_id ?? "turn")}</span>
              <strong>{`${String(item.prompt_chars ?? 0)} / ${String(item.prompt_budget_chars ?? 0)} chars`}</strong>
            </summary>
            <pre>{jsonPreview(item)}</pre>
          </details>
        ))}
        {!recentContextDecisions.length ? (
          <div className="fa-observability-empty is-compact">
            {isChineseUi ? "还没有 context_budget_decision trajectory 记录。" : "No context budget records yet."}
          </div>
        ) : null}
      </section>

      <section className="fa-observability-detail-block fa-agent-role-trajectory">
        <div className="fa-observability-panel-header">
          <div>
            <strong>{isChineseUi ? "Tool Router Trajectory" : "Tool Router Trajectory"}</strong>
            <h2>{isChineseUi ? "最近工具路由记录" : "Recent Tool Route Records"}</h2>
          </div>
          <span>{toolRouteDecisions.data?.trajectory_available ? `${toolRouteDecisions.data.count} records` : "not available"}</span>
        </div>
        {recentToolRouteItems.map((item, index) => (
          <details className="fa-agent-role-trajectory-row" key={`tool-route-${index}`}>
            <summary>
              <span>{String(item.turn_id ?? "turn")}</span>
              <strong>{`${String(item.role ?? "role")} / ${String(item.tool_policy ?? "policy")}`}</strong>
            </summary>
            <pre>{jsonPreview(item)}</pre>
          </details>
        ))}
        {!recentToolRouteItems.length ? (
          <div className="fa-observability-empty is-compact">
            {isChineseUi ? "还没有 tool_route_plan trajectory 记录。" : "No tool_route_plan trajectory records yet."}
          </div>
        ) : null}
      </section>

      <section className="fa-observability-detail-block fa-agent-role-trajectory">
        <div className="fa-observability-panel-header">
          <div>
            <strong>{isChineseUi ? "Trajectory" : "Trajectory"}</strong>
            <h2>{isChineseUi ? "最近决策记录" : "Recent Decision Records"}</h2>
          </div>
          <span>{decisions.data?.trajectory_available ? `${decisions.data.count} records` : "not available"}</span>
        </div>
        {decisions.data?.trajectory_error ? (
          <div className="fa-inline-notice is-danger">{decisions.data.trajectory_error}</div>
        ) : null}
        <div className="fa-agent-role-trajectory-list">
          {recentDecisionItems.map((item, index) => {
            const record = asRecord(item);
            return (
              <details className="fa-agent-role-trajectory-row" key={`${record.turn_id}-${index}`}>
                <summary>
                  <span>{String(record.turn_id ?? "turn")}</span>
                  <strong>{String(record.route_reason ?? "role route plan")}</strong>
                </summary>
                <pre>{jsonPreview(record)}</pre>
              </details>
            );
          })}
          {!recentDecisionItems.length ? (
            <div className="fa-observability-empty is-compact">
              {isChineseUi
                ? "还没有带 role_route_plan 的 trajectory 记录。"
                : "No trajectory records with role_route_plan yet."}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
