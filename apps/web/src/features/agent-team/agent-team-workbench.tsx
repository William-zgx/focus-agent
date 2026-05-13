import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { AgentTeamCockpit } from "./agent-team-cockpit";
import { CreateSessionPanel } from "./agent-team-workbench-create";
import { AdvancedDetailsPanel } from "./agent-team-workbench-merge-handoff";
import { useAgentTeamWorkbenchViewModel } from "./agent-team-workbench-view-model";
import { errorMessage } from "./agent-team-workbench-utils";
import {
  useAgentTeamMergeDecision,
  useAgentTeamMergeProposal,
  useAgentTeamSession,
  useCancelAgentTeamSession,
  usePlanAgentTeamSession,
  useRunAgentTeamSession,
} from "./use-agent-team";

type MissionRefineRequest = Partial<{
  focus: string;
  granularity: string;
}>;

export function AgentTeamWorkbench({ sessionId }: { sessionId: string | null }) {
  const { isChineseUi } = useShellUi();
  const sessionQuery = useAgentTeamSession(sessionId);
  const planSession = usePlanAgentTeamSession(sessionId);
  const runSession = useRunAgentTeamSession(sessionId);
  const cancelSession = useCancelAgentTeamSession(sessionId);
  const mergeProposal = useAgentTeamMergeProposal(sessionId);
  const mergeDecision = useAgentTeamMergeDecision(sessionId);
  const workbenchVm = useAgentTeamWorkbenchViewModel({
    isChineseUi,
    mergeProposalData: mergeProposal.data,
    sessionData: sessionQuery.data,
  });
  const {
    activeBundle,
    advancedMeta,
    displayTitle,
    fallbackPlan,
    finalResultState,
    missionProgress,
    planningMetadata,
    primaryAction,
    queuedTasks,
    readyTasks,
    riskItems,
    runningTasks,
    tasks,
    view,
  } = workbenchVm;
  const [advancedDetailsOpen, setAdvancedDetailsOpen] = useState(false);

  useEffect(() => {
    setAdvancedDetailsOpen(false);
  }, [sessionId]);

  if (!sessionId) return <CreateSessionPanel />;

  if (sessionQuery.isLoading) {
    return (
      <div className="fa-route-state">
        <div className="fa-route-state-card">
          <p className="fa-route-state-title">{isChineseUi ? "正在加载 Agent Team..." : "Loading Agent Team..."}</p>
        </div>
      </div>
    );
  }

  if (sessionQuery.error || !view) {
    return (
      <div className="fa-route-state">
        <div className="fa-route-state-card">
          <p className="fa-route-state-title">
            {isChineseUi ? "无法加载 Agent Team Session" : "Unable to load Agent Team session"}
          </p>
          <p>{errorMessage(sessionQuery.error, isChineseUi ? "返回的数据为空。" : "The response was empty.")}</p>
          <Link className="fa-route-state-link" to="/agent-team">
            {isChineseUi ? "创建新的 Session" : "Create a new session"}
          </Link>
        </div>
      </div>
    );
  }

  const session = view.session;
  const refineOptions = isChineseUi
    ? [
        { label: "调整为更细拆解", request: { granularity: "detailed" } },
        { label: "调整为更粗拆解", request: { granularity: "coarse" } },
        { label: "调整为偏实现", request: { focus: "implementation" } },
        { label: "调整为偏验证", request: { focus: "verification" } },
      ]
    : [
        { label: "More detailed", request: { granularity: "detailed" } },
        { label: "Coarser", request: { granularity: "coarse" } },
        { label: "Implementation", request: { focus: "implementation" } },
        { label: "Verification", request: { focus: "verification" } },
      ];
  const generatePlan = () => planSession.mutate({ create_branches: true });
  const replanMission = () => planSession.mutate({ create_branches: true, replace_existing: true });
  const adjustMissionBreakdown = () =>
    planSession.mutate({ create_branches: true, replace_existing: true, granularity: "balanced", focus: "auto" });
  const runMission = (taskIds?: string[]) =>
    runSession.mutate({
      run_ready_only: true,
      task_ids: taskIds?.length ? taskIds : readyTasks.map((task) => task.task_id),
    });
  const cancelMission = () => cancelSession.mutate();
  const confirmAndReplanMission = () => {
    const message = isChineseUi
      ? "重新拆解会替换当前任务列表，已完成的任务产出仍会留在 Inspector 中。确定继续？"
      : "Replanning will replace the current task list. Completed outputs remain in Inspector. Continue?";
    if (!window.confirm(message)) return;
    replanMission();
  };
  const confirmAndAdjustMissionBreakdown = () => {
    const message = isChineseUi
      ? "调整拆解会重新生成任务列表。确定继续？"
      : "Adjusting the breakdown will regenerate the task list. Continue?";
    if (!window.confirm(message)) return;
    adjustMissionBreakdown();
  };
  const confirmAndCancelMission = () => {
    const message = isChineseUi
      ? "取消 Mission 会停止继续调度任务；已在模型调用中的任务会合作式结束。确定取消？"
      : "Cancelling stops further scheduling; tasks already in a model call finish cooperatively. Cancel mission?";
    if (!window.confirm(message)) return;
    cancelMission();
  };
  const refineMission = (request: MissionRefineRequest) => {
    const message = isChineseUi
      ? "这会按新的偏好重新拆解任务。确定继续？"
      : "This will replan tasks with the new preference. Continue?";
    if (!window.confirm(message)) return;
    planSession.mutate({
      create_branches: true,
      replace_existing: true,
      ...request,
    });
  };
  const generateResult = () => mergeProposal.mutate();
  const toggleAdvancedDetails = () => setAdvancedDetailsOpen((open) => !open);
  const primaryActionBusy =
    (primaryAction.kind === "generate_plan" && planSession.isPending) ||
    (primaryAction.kind === "run_mission" && runSession.isPending) ||
    ((primaryAction.kind === "generate_result" || primaryAction.kind === "regenerate_result") && mergeProposal.isPending);
  const primaryActionLabel = primaryActionBusy
    ? isChineseUi
      ? "处理中..."
      : "Working..."
    : workbenchVm.isPlanReview && primaryAction.kind === "run_mission"
      ? isChineseUi
        ? "确认并开始"
        : "Confirm and start"
      : primaryAction.label;
  const primaryActionDisabled = primaryActionBusy || Boolean(primaryAction.disabledReason);
  const canCancelMission =
    !cancelSession.isPending &&
    (session.status === "planning" ||
      session.status === "running" ||
      (queuedTasks?.length ?? 0) > 0 ||
      (runningTasks?.length ?? 0) > 0 ||
      (missionProgress.queued ?? 0) > 0);
  const executionMode = executionModeForWorkbench(view.outputs ?? [], isChineseUi, view.run);
  const runPrimaryAction = () => {
    if (primaryActionDisabled) return;
    if (primaryAction.kind === "generate_plan") {
      generatePlan();
      return;
    }
    if (primaryAction.kind === "run_mission") {
      runMission();
      return;
    }
    if (primaryAction.kind === "generate_result" || primaryAction.kind === "regenerate_result") {
      generateResult();
    }
  };
  const confirmFinalResult = () => {
    if (!finalResultState.deliverable || mergeDecision.isPending) return;
    mergeDecision.mutate({
      accepted_tasks: tasks.map((task) => task.task_id),
      apply: true,
      next_action: "merge",
      rationale: isChineseUi
        ? "用户已在 Agent Team Cockpit 中确认最终结果可交付。"
        : "The user approved the deliverable final result in Agent Team Cockpit.",
      rejected_tasks: [],
    });
  };
  const cockpitViewModel = {
    ...workbenchVm,
    primaryAction: {
      ...primaryAction,
      busy: primaryActionBusy,
      label: primaryActionLabel,
    },
  };

  return (
    <div className="fa-agent-team-layout fa-agent-team-workspace-shell fa-agent-team-stage fa-agent-team-guided-layout">
      <InlineMutationError
        error={cancelSession.error}
        fallback={isChineseUi ? "取消 Mission 失败。" : "Failed to cancel mission."}
      />
      <InlineMutationError
        error={planSession.error}
        fallback={isChineseUi ? "生成或调整计划失败。" : "Failed to generate or adjust the plan."}
      />
      <InlineMutationError
        error={mergeProposal.error}
        fallback={isChineseUi ? "生成最终结果失败。" : "Failed to generate final result."}
      />
      <InlineMutationError
        error={mergeDecision.error}
        fallback={isChineseUi ? "确认最终结果失败。" : "Failed to approve final result."}
      />

      {fallbackPlan ? (
        <div className="fa-agent-team-plan-banner">
          <strong>{isChineseUi ? "模型规划不可用，已使用保守协作方案" : "Model planning is unavailable, so a conservative collaboration plan was used"}</strong>
          {session.planning_error ? <span {...tooltipProps(session.planning_error)}>{session.planning_error}</span> : null}
        </div>
      ) : null}

      <AgentTeamCockpit
        actions={{
          confirmResultPending: mergeDecision.isPending,
          onConfirmResult: confirmFinalResult,
          onGeneratePlan: generatePlan,
          onGenerateResult: generateResult,
          onPrimaryAction: runPrimaryAction,
          onRunReadyTasks: runMission,
          onSelectTask: workbenchVm.setSelectedTaskId,
        }}
        inspector={{
          isOpen: advancedDetailsOpen,
          onToggle: toggleAdvancedDetails,
        }}
        session={view}
        viewModel={cockpitViewModel}
      />

      <section className="fa-agent-team-cockpit-secondary-bar">
        <span className="fa-agent-team-execution-mode">{executionMode}</span>
        <Link
          className="fa-agent-team-cockpit-button is-secondary"
          params={{ conversationId: session.root_thread_id, threadId: session.root_thread_id }}
          to="/c/$conversationId/t/$threadId"
        >
          {isChineseUi ? "返回来源对话" : "Back to source"}
        </Link>
        <details className="fa-agent-team-more-menu">
          <summary className="fa-agent-team-cockpit-button is-secondary">{isChineseUi ? "更多" : "More"}</summary>
          <div className="fa-agent-team-more-menu-panel">
            <button disabled={planSession.isPending} onClick={tasks.length ? confirmAndReplanMission : generatePlan} type="button">
              {tasks.length ? (isChineseUi ? "重新拆解" : "Replan") : isChineseUi ? "生成方案" : "Generate plan"}
            </button>
            <button disabled={planSession.isPending} onClick={confirmAndAdjustMissionBreakdown} type="button">
              {isChineseUi ? "调整拆解" : "Adjust breakdown"}
            </button>
            <button disabled={mergeProposal.isPending} onClick={generateResult} type="button">
              {isChineseUi ? "生成最终结果" : "Generate final result"}
            </button>
            <div className="fa-agent-team-menu-divider" role="separator" />
            <button
              className="is-danger"
              disabled={!canCancelMission}
              onClick={confirmAndCancelMission}
              type="button"
            >
              {cancelSession.isPending ? (isChineseUi ? "取消中..." : "Cancelling...") : isChineseUi ? "取消 Mission" : "Cancel mission"}
            </button>
            <div className="fa-agent-team-menu-divider" role="separator" />
            {refineOptions.map((option) => (
              <button
                disabled={planSession.isPending}
                key={option.label}
                onClick={() => refineMission(option.request)}
                type="button"
              >
                {option.label}
              </button>
            ))}
            <div className="fa-agent-team-menu-divider" role="separator" />
            <button
              aria-controls="agent-team-cockpit-inspector"
              aria-expanded={advancedDetailsOpen}
              onClick={toggleAdvancedDetails}
              type="button"
            >
              Inspector
            </button>
          </div>
        </details>
      </section>

      {advancedDetailsOpen ? (
        <div className="fa-agent-team-inspector-overlay is-open" onClick={() => setAdvancedDetailsOpen(false)}>
          <aside
            aria-label={isChineseUi ? "Agent Team Inspector" : "Agent Team Inspector"}
            className="fa-agent-team-inspector-drawer"
            id="agent-team-cockpit-inspector"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className="fa-agent-team-inspector-header">
              <div>
                <span>Inspector</span>
                <strong>{displayTitle || session.session_id}</strong>
              </div>
              <button className="fa-agent-team-cockpit-button is-secondary" onClick={toggleAdvancedDetails} type="button">
                {isChineseUi ? "关闭" : "Close"}
              </button>
            </div>
            <AdvancedDetailsPanel
              artifacts={advancedMeta.artifacts}
              bundle={activeBundle}
              changedFiles={advancedMeta.changedFiles}
              dag={advancedMeta.dag}
              evidenceItems={advancedMeta.rawEvidence.evidenceItems}
              openQuestions={advancedMeta.openQuestions}
              planningMetadata={{
                source: planningMetadata.source,
                planner_model_id: planningMetadata.model,
                generated_at: planningMetadata.generatedAt,
                task_count: planningMetadata.taskCount,
                rationale: advancedMeta.planning.rationale,
                plan_hash: advancedMeta.planning.planHash,
                error: advancedMeta.planning.error,
              }}
              outputs={view.outputs ?? []}
              riskItems={riskItems}
              tasks={tasks}
            />
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function InlineMutationError({ error, fallback }: { error: Error | null; fallback: string }) {
  if (!error) return null;
  return <div className="fa-inline-notice is-danger">{errorMessage(error, fallback)}</div>;
}

function executionModeForWorkbench(
  outputs: Array<{ metadata?: Record<string, unknown> }>,
  isChineseUi: boolean,
  runMetadata?: { execution_mode?: unknown } | null,
) {
  const values = outputs.flatMap((output) => {
    const metadata = isRecord(output.metadata) ? output.metadata : {};
    const execution = isRecord(metadata.execution) ? metadata.execution : {};
    const run = isRecord(metadata.run) ? metadata.run : {};
    return [execution.execution_mode, run.execution_mode, metadata.execution_mode];
  });
  if (runMetadata?.execution_mode) values.push(runMetadata.execution_mode);
  const normalized = values.map(stringFromUnknown).find(Boolean)?.toLowerCase();
  if (normalized === "fake") return isChineseUi ? "模拟执行" : "Simulated execution";
  if (normalized === "background") return isChineseUi ? "后台执行" : "Background execution";
  if (normalized === "inline" || normalized === "observe") return isChineseUi ? "真实模型执行" : "Real model execution";
  return isChineseUi ? "执行模式待确认" : "Execution mode pending";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}
