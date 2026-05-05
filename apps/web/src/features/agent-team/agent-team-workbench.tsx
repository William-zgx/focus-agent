import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { CreateSessionPanel } from "./agent-team-workbench-create";
import { AdvancedDetailsPanel, PreMergeCheckPanel } from "./agent-team-workbench-merge-handoff";
import { TaskDetailPanel, TaskLanesPanel } from "./agent-team-workbench-task-lanes";
import { useAgentTeamWorkbenchViewModel } from "./agent-team-workbench-view-model";
import { errorMessage } from "./agent-team-workbench-utils";
import {
  useAgentTeamMergeProposal,
  useAgentTeamSession,
  usePlanAgentTeamSession,
  useRunAgentTeamSession,
} from "./use-agent-team";

type MissionStageState = {
  label: string;
  help?: string;
  tone?: string;
};

type MissionHintState = {
  label: string;
  help?: string;
};

type MissionProgressState = {
  total?: number;
  done?: number;
  completed?: number;
  running?: number;
  blocked?: number;
  ready?: number;
  percent?: number;
};

export function AgentTeamWorkbench({ sessionId }: { sessionId: string | null }) {
  const { isChineseUi } = useShellUi();
  const sessionQuery = useAgentTeamSession(sessionId);
  const planSession = usePlanAgentTeamSession(sessionId);
  const runSession = useRunAgentTeamSession(sessionId);
  const mergeProposal = useAgentTeamMergeProposal(sessionId);
  const workbenchVm = useAgentTeamWorkbenchViewModel({
    isChineseUi,
    mergeProposalData: mergeProposal.data,
    sessionData: sessionQuery.data,
  });
  const {
    activeBundle,
    advancedMeta,
    changedFiles,
    displayTitle,
    evidenceItems,
    fallbackPlan,
    missionProgress,
    nextStep,
    planningMetadata,
    primaryAction,
    readyTasks,
    riskItems,
    selectedTask,
    setSelectedTaskId,
    tasks,
    userFacingResult,
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
  const uxState = workbenchVm as typeof workbenchVm & {
    missionStage?: string | MissionStageState;
    nextStepHint?: string | MissionHintState;
    missionProgress?: MissionProgressState;
  };
  const refineOptions = isChineseUi
    ? [
        { label: "更细", request: { granularity: "detailed" } },
        { label: "更粗", request: { granularity: "coarse" } },
        { label: "偏实现", request: { focus: "implementation" } },
        { label: "偏验证", request: { focus: "verification" } },
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
  const runMission = () => runSession.mutate({ run_ready_only: true, task_ids: readyTasks.map((task) => task.task_id) });
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
    : primaryAction.label;
  const primaryActionDisabled = primaryActionBusy || Boolean(primaryAction.disabledReason);
  const missionStage = normalizeMissionStage(
    uxState.missionStage,
    fallbackMissionStage({
      activeBundle: Boolean(activeBundle),
      isChineseUi,
      progress: missionProgress,
    }),
  );
  const nextStepHint = normalizeMissionHint(uxState.nextStepHint, {
    label: activeBundle ? userFacingResult.nextActionLabel : nextStep.label,
    help: activeBundle ? nextStep.help : primaryAction.help,
  });
  const guidedMissionProgress = normalizeMissionProgress(uxState.missionProgress, missionProgress);
  const missionStatusText = nextStepHint.label;
  const missionStatusHelp = nextStepHint.help ?? primaryAction.help;
  const executionMode = executionModeForWorkbench(view.outputs ?? [], isChineseUi);
  const allTasksComplete =
    (guidedMissionProgress.total ?? 0) > 0 &&
    (guidedMissionProgress.done ?? 0) >= (guidedMissionProgress.total ?? 0) &&
    !(guidedMissionProgress.running ?? 0) &&
    !(guidedMissionProgress.blocked ?? 0);
  const canGenerateResult = Boolean(activeBundle) || allTasksComplete;
  const primaryActionClassName = [
    "fa-agent-team-button",
    "fa-agent-team-primary-action",
    "is-primary",
    primaryActionBusy ? "is-loading" : "",
    primaryActionDisabled ? "is-disabled" : "",
  ]
    .filter(Boolean)
    .join(" ");
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

  return (
    <div className="fa-agent-team-layout fa-agent-team-workspace-shell fa-agent-team-guided-layout">
      <section className="fa-agent-team-mission-header">
        <div className="fa-agent-team-mission-copy">
          <span className="fa-observability-kicker">
            {isChineseUi ? "Agent Team · Mission Runner" : "Agent Team · Mission Runner"}
          </span>
          <h1 {...tooltipProps(session.goal)}>
            {isChineseUi
              ? `Mission：${displayTitle || session.session_id}`
              : `Mission: ${displayTitle || session.session_id}`}
          </h1>
          <p {...tooltipProps(missionStatusHelp)}>{missionStatusText}</p>
          <span className="fa-agent-team-execution-mode">{executionMode}</span>
        </div>
        <div className="fa-agent-team-mission-actions">
          <button
            aria-busy={primaryActionBusy}
            className={primaryActionClassName}
            disabled={primaryActionDisabled}
            onClick={runPrimaryAction}
            type="button"
            {...tooltipProps(primaryAction.disabledReason ?? primaryAction.help)}
          >
            {primaryActionLabel}
          </button>
          <details className="fa-agent-team-more-menu">
            <summary className="fa-agent-team-button is-secondary">{isChineseUi ? "更多" : "More"}</summary>
            <div className="fa-agent-team-more-menu-panel">
              <Link
                params={{ conversationId: session.root_thread_id, threadId: session.root_thread_id }}
                to="/c/$conversationId/t/$threadId"
              >
                {isChineseUi ? "返回来源对话" : "Back to source"}
              </Link>
              <button
                className="is-danger"
                disabled={planSession.isPending || !tasks.length}
                onClick={replanMission}
                type="button"
              >
                {isChineseUi ? "重新拆解" : "Replan"}
              </button>
              <button disabled={planSession.isPending} onClick={adjustMissionBreakdown} type="button">
                {isChineseUi ? "调整拆解" : "Adjust breakdown"}
              </button>
              <div className="fa-agent-team-menu-divider" role="separator" />
              {refineOptions.map((option) => (
                <button
                  disabled={planSession.isPending}
                  key={option.label}
                  onClick={() =>
                    planSession.mutate({
                      create_branches: true,
                      replace_existing: true,
                      ...option.request,
                    })
                  }
                  type="button"
                >
                  {option.label}
                </button>
              ))}
              <div className="fa-agent-team-menu-divider" role="separator" />
              <button
                aria-controls="agent-team-advanced-details"
                aria-expanded={advancedDetailsOpen}
                onClick={toggleAdvancedDetails}
                type="button"
              >
                {isChineseUi ? "高级详情" : "Advanced details"}
              </button>
            </div>
          </details>
        </div>
      </section>

      <section className={`fa-agent-team-mission-progress is-${missionStage.tone ?? "neutral"}`.trim()}>
        <div className="fa-agent-team-progress-lead">
          <span>{isChineseUi ? "Mission 进度" : "Mission progress"}</span>
          <strong {...tooltipProps(missionStage.help)}>{missionStage.label}</strong>
          <p {...tooltipProps(missionStatusHelp)}>{missionStatusText}</p>
        </div>
        <div className="fa-agent-team-progress-meter" aria-hidden="true">
          <span style={{ width: `${missionProgressPercent(guidedMissionProgress)}%` }} />
        </div>
        <div className="fa-agent-team-progress-overview">
          <div>
            <span>{isChineseUi ? "任务" : "Tasks"}</span>
            <strong>{guidedMissionProgress.done ?? 0}/{guidedMissionProgress.total ?? 0}</strong>
          </div>
          <div>
            <span>{isChineseUi ? "就绪" : "Ready"}</span>
            <strong>{guidedMissionProgress.ready ?? 0}</strong>
          </div>
          <div>
            <span>{isChineseUi ? "正在运行" : "Running"}</span>
            <strong>{guidedMissionProgress.running ?? 0}</strong>
          </div>
          <div>
            <span>{isChineseUi ? "需要处理" : "Needs attention"}</span>
            <strong>{guidedMissionProgress.blocked ?? 0}</strong>
          </div>
        </div>
      </section>

      {fallbackPlan ? (
        <div className="fa-agent-team-plan-banner">
          <strong>{isChineseUi ? "模型规划不可用，已使用保守协作方案" : "Model planning is unavailable, so a conservative collaboration plan was used"}</strong>
          {session.planning_error ? <span {...tooltipProps(session.planning_error)}>{session.planning_error}</span> : null}
        </div>
      ) : null}

      <div className="fa-agent-team-guided-grid fa-agent-team-stage">
        <section className="fa-agent-team-task-timeline-panel" aria-label={isChineseUi ? "任务时间线" : "Task timeline"}>
          <TaskLanesPanel
            artifacts={view.artifacts ?? []}
            dispatchError={planSession.error}
            dispatchPending={planSession.isPending}
            onGeneratePlan={tasks.length ? replanMission : generatePlan}
            onSelectTask={setSelectedTaskId}
            outputs={view.outputs ?? []}
            rootThreadId={session.root_thread_id}
            selectedTaskId={selectedTask?.task_id ?? null}
            taskCount={tasks.length}
            tasks={tasks}
          />

          <div className="fa-agent-team-task-detail-shell">
            <TaskDetailPanel
              artifacts={view.artifacts ?? []}
              outputs={view.outputs ?? []}
              selectedTask={selectedTask}
              tasks={tasks}
            />
          </div>
        </section>

        <section className="fa-agent-team-mission-result-panel" aria-label={isChineseUi ? "Agent Team 最终答案" : "Agent Team final answer"}>
          <PreMergeCheckPanel
            bundle={activeBundle}
            error={mergeProposal.error}
            isGenerating={mergeProposal.isPending}
            changedFiles={changedFiles}
            evidenceItems={evidenceItems}
            riskItems={riskItems}
            canGenerate={canGenerateResult}
            nextStepHint={nextStepHint}
            onGenerate={generateResult}
          />
        </section>
      </div>

      <details
        className="fa-agent-team-advanced-shell fa-agent-team-guided-advanced"
        id="agent-team-advanced-details"
        onToggle={(event) => setAdvancedDetailsOpen(event.currentTarget.open)}
        open={advancedDetailsOpen}
      >
        <summary>{isChineseUi ? "高级详情" : "Advanced details"}</summary>
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
      </details>
    </div>
  );
}

function normalizeMissionStage(value: string | MissionStageState | undefined, fallback: MissionStageState) {
  if (typeof value === "string") {
    const label = value.trim();
    return label ? { ...fallback, label } : fallback;
  }
  if (!isRecord(value)) return fallback;
  const label = stringFromUnknown(value.label);
  return {
    label: label || fallback.label,
    help: stringFromUnknown(value.help) || fallback.help,
    tone: stringFromUnknown(value.tone) || fallback.tone,
  };
}

function normalizeMissionHint(value: string | MissionHintState | undefined, fallback: MissionHintState) {
  if (typeof value === "string") {
    const label = value.trim();
    return label ? { ...fallback, label } : fallback;
  }
  if (!isRecord(value)) return fallback;
  const label = stringFromUnknown(value.label);
  return {
    label: label || fallback.label,
    help: stringFromUnknown(value.help) || fallback.help,
  };
}

function normalizeMissionProgress(value: MissionProgressState | undefined, fallback: MissionProgressState) {
  const source = isRecord(value) ? value : {};
  return {
    total: numberFromUnknown(source.total, fallback.total ?? 0),
    done: numberFromUnknown(source.done ?? source.completed, fallback.done ?? 0),
    running: numberFromUnknown(source.running, fallback.running ?? 0),
    blocked: numberFromUnknown(source.blocked, fallback.blocked ?? 0),
    ready: numberFromUnknown(source.ready, fallback.ready ?? 0),
    percent: numberFromUnknown(source.percent, fallback.percent),
  };
}

function missionProgressPercent(progress: MissionProgressState) {
  if (typeof progress.percent === "number" && Number.isFinite(progress.percent)) {
    return clampPercent(progress.percent);
  }
  const total = progress.total ?? 0;
  if (total <= 0) return 0;
  return clampPercent(Math.round(((progress.done ?? 0) / total) * 100));
}

function fallbackMissionStage({
  activeBundle,
  isChineseUi,
  progress,
}: {
  activeBundle: boolean;
  isChineseUi: boolean;
  progress: MissionProgressState;
}): MissionStageState {
  const total = progress.total ?? 0;
  const done = progress.done ?? 0;
  const running = progress.running ?? 0;
  const blocked = progress.blocked ?? 0;
  const ready = progress.ready ?? 0;

  if (!total) {
    return {
      label: isChineseUi ? "等待生成 Mission 拆解" : "Ready for mission breakdown",
      help: isChineseUi ? "先把目标拆成可执行任务。" : "Start by splitting the goal into executable tasks.",
      tone: "planning",
    };
  }
  if (running) {
    return {
      label: isChineseUi ? "Mission 正在执行" : "Mission is running",
      help: isChineseUi ? "任务产出、依据和风险会随运行回传。" : "Task outputs, evidence, and risks will appear as work returns.",
      tone: "running",
    };
  }
  if (activeBundle) {
    return {
      label: isChineseUi ? "最终结果已生成" : "Final result is ready",
      help: isChineseUi ? "检查结果、依据和需要注意事项后交付。" : "Review the result, evidence, and needs-attention items before delivery.",
      tone: "result",
    };
  }
  if (done >= total) {
    return {
      label: isChineseUi ? "任务已完成，等待汇总" : "Tasks complete; synthesis is next",
      help: isChineseUi ? "把任务产出收束为用户可读的最终结果。" : "Collect task outputs into a user-facing final result.",
      tone: "result",
    };
  }
  if (blocked && !ready) {
    return {
      label: isChineseUi ? "Mission 需要处理" : "Mission needs attention",
      help: isChineseUi ? "先处理依赖、失败或需要注意的任务。" : "Resolve dependencies, failures, or tasks needing attention first.",
      tone: "needs_attention",
    };
  }
  if (ready) {
    return {
      label: isChineseUi ? "已有任务就绪" : "Tasks are ready",
      help: isChineseUi ? "可以运行依赖已满足的任务。" : "Run tasks whose dependencies are satisfied.",
      tone: "ready",
    };
  }
  return {
    label: isChineseUi ? "等待下一批任务就绪" : "Waiting for the next ready task",
    help: isChineseUi ? "保持在主流程查看任务和结果。" : "Stay in the main flow to review tasks and results.",
    tone: "neutral",
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function numberFromUnknown(value: unknown, fallback: number | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

function executionModeForWorkbench(outputs: Array<{ metadata?: Record<string, unknown> }>, isChineseUi: boolean) {
  const mode = outputs
    .map((output) => {
      const metadata = isRecord(output.metadata) ? output.metadata : {};
      const execution = isRecord(metadata.execution) ? metadata.execution : {};
      const run = isRecord(metadata.run) ? metadata.run : {};
      return stringFromUnknown(execution.execution_mode) || stringFromUnknown(run.execution_mode);
    })
    .find(Boolean);
  const normalized = (mode || "fake").toLowerCase();
  if (normalized === "inline" || normalized === "model") {
    return isChineseUi ? "真实模型执行" : "Real model execution";
  }
  if (normalized === "background") {
    return isChineseUi ? "后台执行" : "Background execution";
  }
  return isChineseUi ? "模拟执行" : "Simulated execution";
}
