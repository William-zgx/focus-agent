import {
  type FocusAgentRoleDecisionListResponse,
  type FocusAgentRoleDryRunResponse,
  type FocusAgentRolePolicyResponse,
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

export function AgentRoleConsolePage() {
  const { client } = useFocusAgent();
  const { isChineseUi } = useShellUi();
  const [message, setMessage] = useState(DEFAULT_DRY_RUN_MESSAGE);
  const [availableTools, setAvailableTools] = useState(
    "search_code,read_file,git_diff,web_search,memory_search,skills_list,skill_view,write_text_artifact",
  );
  const policy = useAgentRolePolicy();
  const decisions = useAgentRoleDecisions();
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
  const dryRunPlan = asRecord(dryRun.data?.plan);
  const dryRunDecisions = asArray(dryRunPlan.decisions);
  const roleModels = useMemo(
    () => Object.entries(policy.data?.role_models ?? {}),
    [policy.data?.role_models],
  );
  const recentDecisionItems = decisions.data?.items ?? [];

  return (
    <div className="fa-observability-layout fa-agent-role-console">
      <section className="fa-observability-hero fa-agent-role-hero">
        <div className="fa-observability-hero-copy">
          <p className="fa-observability-kicker">
            {isChineseUi ? "Agent 决策架构" : "Agent Decision Architecture"}
          </p>
          <h1>{isChineseUi ? "角色路由控制台" : "Role Routing Console"}</h1>
          <p className="fa-observability-hero-text">
            {isChineseUi
              ? "查看当前角色模型策略，预演 Orchestrator 的路由决策，并从 trajectory 中回看最近的 role_route_plan。"
              : "Inspect the active role-model policy, dry-run orchestrator routing, and review recent role_route_plan records from trajectory."}
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
            <Link className="fa-trajectory-workbench-tab fa-observability-route-tab is-active" to="/agent/roles">
              <span>{isChineseUi ? "角色路由" : "Role routing"}</span>
              <strong>{isChineseUi ? "策略 / 预演" : "Policy / dry-run"}</strong>
            </Link>
          </nav>
        </div>
        <div className="fa-observability-hero-grid fa-agent-role-policy-grid">
          <div className="fa-observability-stat-card">
            <span>{isChineseUi ? "状态" : "Status"}</span>
            <strong>{policy.data?.enabled ? "enabled" : "dry-run off"}</strong>
            <p>{isChineseUi ? "默认保持 legacy 执行路径" : "Legacy execution remains unchanged"}</p>
          </div>
          <div className="fa-observability-stat-card">
            <span>{isChineseUi ? "主模型" : "Main model"}</span>
            <strong>{policy.data?.default_model ?? "loading"}</strong>
            <p>{isChineseUi ? "executor 默认回落到主模型" : "Executor falls back to the main model"}</p>
          </div>
          <div className="fa-observability-stat-card">
            <span>{isChineseUi ? "并行上限" : "Parallel cap"}</span>
            <strong>{policy.data?.max_parallel_runs ?? "-"}</strong>
            <p>{isChineseUi ? "只影响路由计划，不触发真实子运行" : "Affects planning only, not real delegated runs"}</p>
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
