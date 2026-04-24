import {
  type FocusAgentCapabilityListResponse,
  type FocusAgentMemoryCuratorDecisionListResponse,
  type FocusAgentMemoryCuratorPolicyResponse,
  type FocusAgentRoleDecisionListResponse,
  type FocusAgentRoleDryRunResponse,
  type FocusAgentRolePolicyResponse,
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
