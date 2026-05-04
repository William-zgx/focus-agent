import {
  type FocusAgentContextPreviewResponse,
  type FocusAgentRoleDryRunResponse,
  type FocusAgentTaskLedgerPlanResponse,
  type FocusAgentToolRouteResponse,
} from "@focus-agent/web-sdk";
import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import {
  useAgentArtifacts,
  useAgentCapabilities,
  useAgentContextArtifacts,
  useAgentContextDecisions,
  useAgentContextPolicy,
  useAgentCriticVerdicts,
  useAgentDelegationPolicy,
  useAgentDelegationRuns,
  useAgentMemoryCuratorDecisions,
  useAgentMemoryCuratorPolicy,
  useAgentModelRouterDecisions,
  useAgentModelRouterPolicy,
  useAgentReviewQueue,
  useAgentRoleDecisions,
  useAgentRolePolicy,
  useAgentSelfRepairFailures,
  useAgentTaskLedgerPolicy,
  useAgentTaskLedgerRuns,
  useAgentToolRouteDecisions,
} from "./agent-role-console-hooks";
import {
  AgentRoleHero,
  EmptyState,
  InlineDangerNotice,
  KeyValueList,
  PanelHeader,
  RawJsonDetails,
  RoleDecisionCards,
  ToolRouteDecisionCards,
  TrajectoryDetailsList,
} from "./agent-role-console-sections";
import {
  CapabilityRegistryPanel,
  ContextArtifactsPanel,
  ContextDecisionsPanel,
  CriticGatePanel,
  DelegationModelRouterPanels,
  RecentDecisionRecordsPanel,
  RepairReviewQueuePanels,
  ToolRouterTrajectoryPanel,
} from "./agent-role-console-trajectory-panels";
import {
  DEFAULT_DRY_RUN_MESSAGE,
  asArray,
  asRecord,
  errorMessage,
  roleLabel,
} from "./agent-role-console-utils";

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
  const taskLedgerPolicy = useAgentTaskLedgerPolicy();
  const taskLedgerRuns = useAgentTaskLedgerRuns();
  const delegatedArtifacts = useAgentArtifacts();
  const criticVerdicts = useAgentCriticVerdicts();
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
  const taskLedgerPreview = useMutation<FocusAgentTaskLedgerPlanResponse, Error>({
    mutationFn: () =>
      client.planAgentTaskLedger({
        message,
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
  const recentTaskLedgerRuns = taskLedgerRuns.data?.items ?? [];
  const recentDelegatedArtifacts = delegatedArtifacts.data?.items ?? [];
  const recentCriticVerdicts = criticVerdicts.data?.items ?? [];
  const contextPreviewDecision = asRecord(contextPreview.data?.decision);
  const contextPreviewBudget = asRecord(contextPreviewDecision.budget);
  const contextPreviewPlan = asRecord(contextPreviewDecision.compression_plan);
  const taskLedgerPreviewLedger = asRecord(taskLedgerPreview.data?.ledger);
  const taskLedgerPreviewTasks = asArray(taskLedgerPreviewLedger.tasks);

  return (
    <div className="fa-observability-layout fa-agent-role-console">
      <AgentRoleHero
        artifactizeLongObservations={contextPolicy.data?.artifactize_long_observations}
        autoPromoteOnMerge={memoryPolicy.data?.auto_promote_on_merge}
        capabilityCount={capabilities.data?.count}
        contextEnabled={contextPolicy.data?.enabled}
        criticGateEnforce={taskLedgerPolicy.data?.critic_gate_enforce}
        delegationEnabled={delegationPolicy.data?.enabled}
        delegationEnforce={delegationPolicy.data?.enforce}
        isChineseUi={isChineseUi}
        memoryEnabled={memoryPolicy.data?.enabled}
        policyEnabled={policy.data?.enabled}
        taskLedgerEnabled={taskLedgerPolicy.data?.enabled}
      />

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <PanelHeader
            eyebrow={isChineseUi ? "Policy" : "Policy"}
            meta={policy.isLoading ? "loading" : `${roleModels.length} roles`}
            title={isChineseUi ? "角色模型映射" : "Role Model Mapping"}
          />
          {policy.error ? (
            <InlineDangerNotice>{errorMessage(policy.error, "Failed to load role policy")}</InlineDangerNotice>
          ) : null}
          <KeyValueList rows={roleModels.map(([role, model]) => ({ label: roleLabel(role), value: model ?? "-" }))} />
          <RawJsonDetails
            summary={isChineseUi ? "查看完整 policy JSON" : "View full policy JSON"}
            value={policy.data ?? {}}
          />
        </div>

        <div className="fa-observability-detail-panel fa-agent-role-panel">
          <PanelHeader
            eyebrow={isChineseUi ? "Dry run" : "Dry run"}
            meta={dryRun.isPending ? "running" : "preview only"}
            title={isChineseUi ? "路由预演" : "Routing Preview"}
          />
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
            <InlineDangerNotice>{errorMessage(dryRun.error, "Dry-run request failed")}</InlineDangerNotice>
          ) : null}
          {dryRun.data ? (
            <RoleDecisionCards decisions={dryRunDecisions} />
          ) : (
            <EmptyState>
              {isChineseUi ? "提交一次 dry-run 后，这里会展示路由决策。" : "Run a dry-run to inspect routing decisions here."}
            </EmptyState>
          )}
        </div>
      </section>

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <PanelHeader
            eyebrow={isChineseUi ? "Memory Curator" : "Memory Curator"}
            meta={memoryPolicy.isLoading ? "loading" : memoryPolicy.data?.conflict_strategy ?? "needs_review"}
            title={isChineseUi ? "分支语义保护" : "Branch Semantic Guard"}
          />
          {memoryPolicy.error ? (
            <InlineDangerNotice>
              {errorMessage(memoryPolicy.error, "Failed to load memory curator policy")}
            </InlineDangerNotice>
          ) : null}
          <KeyValueList
            rows={[
              {
                label: isChineseUi ? "启用状态" : "Enabled",
                value: String(memoryPolicy.data?.enabled ?? false),
              },
              {
                label: isChineseUi ? "合并自动提升" : "Auto promote on merge",
                value: String(memoryPolicy.data?.auto_promote_on_merge ?? true),
              },
              {
                label: isChineseUi ? "冲突策略" : "Conflict strategy",
                value: memoryPolicy.data?.conflict_strategy ?? "needs_review",
              },
            ]}
          />
          <TrajectoryDetailsList
            empty={isChineseUi ? "还没有 memory curator trajectory 记录。" : "No memory curator trajectory records yet."}
            getKey={(_item, index) => `memory-${index}`}
            getSummary={(item) => ({
              label: String(item.branch_id ?? item.turn_id ?? "memory"),
              value: String(item.status ?? "curator decision"),
            })}
            items={recentMemoryItems}
            limit={5}
          />
        </div>

        <div className="fa-observability-detail-panel fa-agent-role-panel">
          <PanelHeader
            eyebrow={isChineseUi ? "Tool Router" : "Tool Router"}
            meta={toolRoute.isPending ? "routing" : "enforced plan"}
            title={isChineseUi ? "能力路由预演" : "Capability Routing"}
          />
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
            <InlineDangerNotice>{errorMessage(toolRoute.error, "Tool route request failed")}</InlineDangerNotice>
          ) : null}
          {toolRoute.data ? (
            <ToolRouteDecisionCards decisions={toolRoutePlanDecisions} />
          ) : (
            <EmptyState>
              {isChineseUi ? "运行一次工具路由后，这里会展示 allow/deny 决策。" : "Run tool routing to inspect allow/deny decisions."}
            </EmptyState>
          )}
        </div>
      </section>

      <DelegationModelRouterPanels
        delegationTrajectoryAvailable={delegationRuns.data?.trajectory_available}
        isChineseUi={isChineseUi}
        modelRouterEnabled={modelRouterPolicy.data?.enabled}
        modelRouterMode={modelRouterPolicy.data?.mode}
        modelRouterRoleModels={modelRouterPolicy.data?.role_models}
        recentDelegationRuns={recentDelegationRuns}
        recentModelRouteItems={recentModelRouteItems}
      />

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <PanelHeader
            eyebrow={isChineseUi ? "Task Ledger" : "Task Ledger"}
            meta={taskLedgerRuns.data?.trajectory_available ? `${recentTaskLedgerRuns.length} tasks` : "not available"}
            title={isChineseUi ? "任务账本与 DAG" : "Task DAG"}
          />
          {taskLedgerPolicy.error ? (
            <InlineDangerNotice>
              {errorMessage(taskLedgerPolicy.error, "Failed to load task ledger policy")}
            </InlineDangerNotice>
          ) : null}
          <KeyValueList
            rows={[
              {
                label: isChineseUi ? "启用状态" : "Enabled",
                value: String(taskLedgerPolicy.data?.enabled ?? false),
              },
              {
                label: isChineseUi ? "Artifact synthesis" : "Artifact synthesis",
                value: String(taskLedgerPolicy.data?.artifact_synthesis_enabled ?? false),
              },
              {
                label: isChineseUi ? "Critic gate" : "Critic gate",
                value: taskLedgerPolicy.data?.critic_gate_enforce
                  ? "enforce"
                  : String(taskLedgerPolicy.data?.critic_gate_enabled ?? false),
              },
            ]}
          />
          <div className="fa-observability-command-bar">
            <button
              className="fa-observability-preset is-primary"
              disabled={taskLedgerPreview.isPending || !message.trim()}
              onClick={() => taskLedgerPreview.mutate()}
              type="button"
            >
              {taskLedgerPreview.isPending
                ? isChineseUi
                  ? "预览中..."
                  : "Planning..."
                : isChineseUi
                  ? "预览任务账本"
                  : "Preview Ledger"}
            </button>
          </div>
          {taskLedgerPreview.error ? (
            <InlineDangerNotice>
              {errorMessage(taskLedgerPreview.error, "Task ledger preview failed")}
            </InlineDangerNotice>
          ) : null}
          {taskLedgerPreview.data ? (
            <TrajectoryDetailsList
              getKey={(_item, index) => `task-ledger-preview-${index}`}
              getSummary={(item) => ({
                label: String(item.role ?? item.task_id ?? "task"),
                value: String(item.status ?? "planned"),
              })}
              items={taskLedgerPreviewTasks}
            />
          ) : null}
          <TrajectoryDetailsList
            empty={
              !taskLedgerPreview.data
                ? isChineseUi
                  ? "还没有 agent_task_ledger trajectory 记录。"
                  : "No agent_task_ledger trajectory records yet."
                : null
            }
            getKey={(_item, index) => `task-ledger-${index}`}
            getSummary={(item) => ({
              label: String(item.role ?? item.task_id ?? "task"),
              value: `${String(item.status ?? "planned")} / retry ${String(item.retry_count ?? 0)}`,
            })}
            items={recentTaskLedgerRuns}
            limit={5}
          />
        </div>

        <div className="fa-observability-detail-panel fa-agent-role-panel">
          <PanelHeader
            eyebrow={isChineseUi ? "Delegated Artifacts" : "Delegated Artifacts"}
            meta={delegatedArtifacts.data?.trajectory_available ? `${recentDelegatedArtifacts.length} artifacts` : "not available"}
            title={isChineseUi ? "产物交接" : "Artifact Handoff"}
          />
          <TrajectoryDetailsList
            empty={isChineseUi ? "还没有 delegated_artifacts trajectory 记录。" : "No delegated artifact records yet."}
            getKey={(_item, index) => `delegated-artifact-${index}`}
            getSummary={(item) => ({
              label: String(item.kind ?? item.title ?? "artifact"),
              value: String(item.status ?? "draft"),
            })}
            items={taskLedgerPreview.data?.artifacts ?? recentDelegatedArtifacts}
            limit={6}
            wrap={false}
          />
        </div>
      </section>

      <CriticGatePanel
        criticTrajectoryAvailable={criticVerdicts.data?.trajectory_available}
        criticVerdictCount={criticVerdicts.data?.count}
        isChineseUi={isChineseUi}
        recentCriticVerdicts={recentCriticVerdicts}
      />

      <RepairReviewQueuePanels
        isChineseUi={isChineseUi}
        recentFailures={recentFailures}
        reviewQueueItems={reviewQueueItems}
        reviewQueueTrajectoryAvailable={reviewQueue.data?.trajectory_available}
        selfRepairTrajectoryAvailable={selfRepairFailures.data?.trajectory_available}
      />

      <section className="fa-agent-role-grid">
        <div className="fa-observability-list-panel fa-agent-role-panel">
          <PanelHeader
            eyebrow={isChineseUi ? "Context Engineering v2" : "Context Engineering v2"}
            meta={contextPolicy.data?.enabled ? "enabled" : "disabled"}
            title={isChineseUi ? "长上下文压缩策略" : "Long Context Policy"}
          />
          {contextPolicy.error ? (
            <InlineDangerNotice>{errorMessage(contextPolicy.error, "Failed to load context policy")}</InlineDangerNotice>
          ) : null}
          <KeyValueList
            rows={[
              {
                label: isChineseUi ? "Tokenizer" : "Tokenizer",
                value: contextPolicy.data?.tokenizer_mode ?? "chars_fallback",
              },
              {
                label: isChineseUi ? "Artifact 阈值" : "Artifact threshold",
                value: contextPolicy.data?.artifact_min_chars ?? 12000,
              },
              {
                label: isChineseUi ? "角色视图" : "Role views",
                value: String(contextPolicy.data?.role_views_enabled ?? false),
              },
            ]}
          />
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
            <InlineDangerNotice>
              {errorMessage(contextPreview.error, "Context preview request failed")}
            </InlineDangerNotice>
          ) : null}
          {contextPreview.data ? (
            <KeyValueList
              rows={[
                {
                  label: isChineseUi ? "Prompt chars" : "Prompt chars",
                  value: String(contextPreviewBudget.prompt_chars ?? 0),
                },
                {
                  label: isChineseUi ? "Over budget" : "Over budget",
                  value: String(contextPreviewBudget.over_budget_chars ?? 0),
                },
                {
                  label: isChineseUi ? "Saved chars" : "Saved chars",
                  value: String(contextPreviewPlan.estimated_saved_chars ?? 0),
                },
              ]}
            />
          ) : (
            <EmptyState>
              {isChineseUi ? "运行一次预览后，这里会展示预算和压缩结果。" : "Run a preview to inspect budget and compression output."}
            </EmptyState>
          )}
        </div>

        <ContextArtifactsPanel
          contextArtifactsTrajectoryAvailable={contextArtifacts.data?.trajectory_available}
          isChineseUi={isChineseUi}
          recentContextArtifacts={recentContextArtifacts}
        />
      </section>

      <CapabilityRegistryPanel
        capabilitiesError={capabilities.error}
        capabilitiesIsLoading={capabilities.isLoading}
        capabilityItems={capabilityItems}
        isChineseUi={isChineseUi}
      />

      <ContextDecisionsPanel
        contextDecisionCount={contextDecisions.data?.count}
        contextDecisionsTrajectoryAvailable={contextDecisions.data?.trajectory_available}
        isChineseUi={isChineseUi}
        recentContextDecisions={recentContextDecisions}
      />

      <ToolRouterTrajectoryPanel
        isChineseUi={isChineseUi}
        recentToolRouteItems={recentToolRouteItems}
        toolRouteDecisionCount={toolRouteDecisions.data?.count}
        toolRouteTrajectoryAvailable={toolRouteDecisions.data?.trajectory_available}
      />

      <RecentDecisionRecordsPanel
        decisionCount={decisions.data?.count}
        decisionsTrajectoryAvailable={decisions.data?.trajectory_available}
        decisionsTrajectoryError={decisions.data?.trajectory_error}
        isChineseUi={isChineseUi}
        recentDecisionItems={recentDecisionItems}
      />
    </div>
  );
}
