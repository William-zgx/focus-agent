import {
  finalAnswerStatusForBundle,
  type AgentTeamWorkbenchFinalPreviewState,
  type AgentTeamWorkbenchFinalResultStateKind,
} from "./agent-team-workbench-derived-state";
import { uniqueNonEmptyStrings, type AgentTeamTaskDisplayState } from "./agent-team-workbench-utils";
import type { AgentTeamMergeBundle, AgentTeamTask } from "./types";

export interface AgentTeamWorkbenchDecisionDockState {
  primaryActionKind: string;
  primaryActionLabel: string;
  primaryActionHelp: string;
  primaryActionDisabledReason?: string;
  nextStepLabel: string;
  nextStepHelp?: string;
  attentionItems: string[];
  evidenceItems: string[];
  riskItems: string[];
  canGenerateResult: boolean;
  canApproveFinal: boolean;
  recommendedTaskId: string | null;
  focusReason: string;
  finalPreviewKind: AgentTeamWorkbenchFinalResultStateKind;
}

export function isPlanReviewState({
  activeBundle,
  taskDisplayStates,
  tasks,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  taskDisplayStates: AgentTeamTaskDisplayState[];
  tasks: AgentTeamTask[];
}) {
  if (!tasks.length || activeBundle) return false;
  return taskDisplayStates.every((state) =>
    state.kind === "ready" || state.kind === "pending" || state.kind === "waiting_dependency",
  );
}

export function decisionDockStateForWorkbench({
  blockedExplanation,
  canGenerateResult,
  finalPreviewState,
  focusReason,
  nextStepHint,
  primaryAction,
  recommendedTaskId,
  riskItems,
  selectedTaskState,
}: {
  blockedExplanation: string | null;
  canGenerateResult: boolean;
  finalPreviewState: AgentTeamWorkbenchFinalPreviewState;
  focusReason: string;
  nextStepHint: { help?: string; label: string };
  primaryAction: ReturnType<typeof primaryActionForWorkbench>;
  recommendedTaskId: string | null;
  riskItems: string[];
  selectedTaskState: AgentTeamTaskDisplayState | null;
}): AgentTeamWorkbenchDecisionDockState {
  const attentionItems = uniqueNonEmptyStrings([
    selectedTaskState?.lastError,
    blockedExplanation,
    ...riskItems.slice(0, 3),
    ...finalPreviewState.warnings,
  ]);
  return {
    primaryActionKind: primaryAction.kind,
    primaryActionLabel: primaryAction.label,
    primaryActionHelp: primaryAction.help,
    primaryActionDisabledReason: primaryAction.disabledReason,
    nextStepLabel: nextStepHint.label,
    nextStepHelp: nextStepHint.help,
    attentionItems,
    evidenceItems: finalPreviewState.evidenceItems,
    riskItems: finalPreviewState.riskItems.length ? finalPreviewState.riskItems : riskItems,
    canGenerateResult,
    canApproveFinal: finalPreviewState.canApprove,
    recommendedTaskId,
    focusReason,
    finalPreviewKind: finalPreviewState.kind,
  };
}

export function primaryActionForWorkbench({
  activeBundle,
  blockedExplanation,
  doneTasksCount,
  isChineseUi,
  readyTasksCount,
  queuedTasksCount,
  runningTasksCount,
  taskDisplayStates,
  tasks,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  blockedExplanation: string | null;
  doneTasksCount: number;
  isChineseUi: boolean;
  readyTasksCount: number;
  queuedTasksCount: number;
  runningTasksCount: number;
  taskDisplayStates: AgentTeamTaskDisplayState[];
  tasks: AgentTeamTask[];
}) {
  const hasActionableIssue = taskDisplayStates.some(isActionableTaskState);

  if (!tasks.length) {
    return {
      kind: "generate_plan",
      label: isChineseUi ? "生成方案" : "Generate plan",
      help: isChineseUi
        ? "先把目标拆成可执行的 Agent Team 任务。"
        : "Start by turning the goal into executable Agent Team tasks.",
    };
  }

  if (runningTasksCount || queuedTasksCount) {
    return {
      kind: "running",
      label: queuedTasksCount && !runningTasksCount ? (isChineseUi ? "排队中..." : "Queued...") : isChineseUi ? "执行中..." : "Running...",
      help: isChineseUi
        ? "Mission 正在执行或排队，等待任务回传产出、依据和需要注意的事项。"
        : "The mission is running or queued; wait for task outputs, evidence, and risks.",
      disabledReason: isChineseUi ? "当前已有任务执行中或排队中" : "A task is already running or queued",
    };
  }

  if (hasActionableIssue) {
    const reason =
      blockedExplanation ??
      (isChineseUi
        ? "有任务需要处理，请查看任务详情后继续。"
        : "A task needs attention. Review task details before continuing.");
    return {
      kind: "blocked",
      label: isChineseUi ? "需要处理" : "Needs attention",
      help: reason,
      disabledReason: reason,
    };
  }

  if (readyTasksCount) {
    return {
      kind: "run_mission",
      label: isChineseUi ? "运行 Mission" : "Run mission",
      help: isChineseUi
        ? "自动运行依赖已满足的任务，并继续推进到下一批可执行任务。"
        : "Run tasks whose dependencies are satisfied and keep advancing to the next ready batch.",
    };
  }

  if (doneTasksCount === tasks.length && !activeBundle) {
    return {
      kind: "generate_result",
      label: isChineseUi ? "生成最终结果" : "Generate final result",
      help: isChineseUi
        ? "所有任务已完成，将产出、依据和需要注意的事项整理成最终结果。"
        : "All tasks are complete; package outputs, evidence, and risks into the final result.",
    };
  }

  if (activeBundle) {
    return {
      kind: "regenerate_result",
      label: isChineseUi ? "重新生成结果" : "Regenerate result",
      help: isChineseUi
        ? "已有最终结果，可基于最新任务状态重新汇总。"
        : "A final result already exists; regenerate it from the latest task state.",
    };
  }

  return {
    kind: "blocked",
    label: isChineseUi ? "等待任务就绪" : "Waiting for ready tasks",
    help: isChineseUi
      ? "当前没有可运行任务，请检查任务依赖或等待前置任务完成。"
      : "No task is ready to run. Check dependencies or wait for prerequisite work to finish.",
    disabledReason: isChineseUi ? "暂无就绪任务" : "No ready tasks",
  };
}

export function missionStageForWorkbench({
  activeBundle,
  blockedExplanation,
  doneTasksCount,
  isChineseUi,
  readyTasksCount,
  queuedTasksCount,
  runningTasksCount,
  taskDisplayStates,
  tasks,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  blockedExplanation: string | null;
  doneTasksCount: number;
  isChineseUi: boolean;
  readyTasksCount: number;
  queuedTasksCount: number;
  runningTasksCount: number;
  taskDisplayStates: AgentTeamTaskDisplayState[];
  tasks: AgentTeamTask[];
}) {
  if (!tasks.length) {
    return {
      kind: "plan_needed",
      label: isChineseUi ? "待生成方案" : "Plan needed",
      help: isChineseUi
        ? "先把 Mission 目标拆成可执行任务。"
        : "Start by splitting the mission goal into executable tasks.",
      tone: "neutral",
    };
  }

  if (runningTasksCount || queuedTasksCount) {
    return {
      kind: queuedTasksCount && !runningTasksCount ? "queued" : "running",
      label: queuedTasksCount && !runningTasksCount ? (isChineseUi ? "排队中" : "Queued") : isChineseUi ? "执行中" : "Running",
      help: isChineseUi ? "任务正在执行或排队，等待产出回传。" : "Tasks are running or queued; wait for outputs to return.",
      tone: "neutral",
    };
  }

  if (taskDisplayStates.some(isActionableTaskState)) {
    return {
      kind: "needs_attention",
      label: isChineseUi ? "需要处理" : "Needs attention",
      help:
        blockedExplanation ??
        (isChineseUi
          ? "有任务需要处理，请查看任务详情。"
          : "Some tasks need attention. Review task details."),
      tone: "warning",
    };
  }

  if (readyTasksCount) {
    return {
      kind: "ready",
      label: isChineseUi ? "可运行" : "Ready",
      help: isChineseUi ? "已有任务可运行，可以推进下一步。" : "At least one task is ready to run next.",
      tone: "neutral",
    };
  }

  if (doneTasksCount === tasks.length && !activeBundle) {
    return {
      kind: "ready_for_result",
      label: isChineseUi ? "待生成最终结果" : "Ready for final result",
      help: isChineseUi ? "所有任务已完成，可以生成最终结果。" : "All tasks are complete and ready for final synthesis.",
      tone: "success",
    };
  }

  if (activeBundle) {
    const finalStatus = finalAnswerStatusForBundle(activeBundle);
    if (finalStatus === "placeholder") {
      return {
        kind: "simulated_result",
        label: isChineseUi ? "模拟结果已生成" : "Simulated result generated",
        help: isChineseUi
          ? "当前只验证了协作流程，没有生成可交付的真实最终答案。"
          : "The collaboration flow was validated, but no deliverable final answer was generated.",
        tone: "warning",
      };
    }
    if (finalStatus === "blocked" || finalStatus === "error") {
      return {
        kind: "result_needs_attention",
        label: isChineseUi ? "最终结果需要处理" : "Final result needs attention",
        help: isChineseUi
          ? "结果汇总未能形成可交付答案，请查看右侧原因和下一步。"
          : "Synthesis did not produce a deliverable answer; review the reason and next step.",
        tone: finalStatus === "error" ? "danger" : "warning",
      };
    }
    return {
      kind: "result_ready",
      label: isChineseUi ? "结果已生成" : "Result ready",
      help: isChineseUi ? "最终结果已生成，可查看或重新生成。" : "A final result is available to review or regenerate.",
      tone: "success",
    };
  }

  if (taskDisplayStates.some((state) => state.kind === "waiting_dependency")) {
    return {
      kind: "waiting_dependency",
      label: isChineseUi ? "等待前置任务" : "Waiting for dependencies",
      help: isChineseUi ? "部分任务需要等前置任务完成后再运行。" : "Some tasks are waiting for prerequisite work.",
      tone: "neutral",
    };
  }

  return {
    kind: "waiting_start",
    label: isChineseUi ? "等待开始" : "Waiting to start",
    help: isChineseUi ? "任务已创建，等待开始执行。" : "Tasks exist and are waiting to start.",
    tone: "neutral",
  };
}

export function blockedExplanationForWorkbench({
  isChineseUi,
  taskDisplayStates,
}: {
  isChineseUi: boolean;
  taskDisplayStates: AgentTeamTaskDisplayState[];
}) {
  const failedCount = taskDisplayStates.filter((state) => state.kind === "failed").length;
  if (failedCount) {
    return isChineseUi
      ? `${failedCount} 个任务执行失败，请查看任务详情后处理。`
      : `${failedCount} task${failedCount === 1 ? "" : "s"} failed. Review task details before continuing.`;
  }

  const needsAttentionCount = taskDisplayStates.filter((state) => state.kind === "needs_attention").length;
  if (needsAttentionCount) {
    return isChineseUi
      ? `${needsAttentionCount} 个任务需要处理，请查看错误信息后继续。`
      : `${needsAttentionCount} task${needsAttentionCount === 1 ? "" : "s"} need attention. Review the error before continuing.`;
  }

  const waitingDependencyCount = taskDisplayStates.filter((state) => state.kind === "waiting_dependency").length;
  if (waitingDependencyCount) {
    return isChineseUi
      ? `${waitingDependencyCount} 个任务正在等待前置任务完成。`
      : `${waitingDependencyCount} task${waitingDependencyCount === 1 ? "" : "s"} are waiting for dependencies.`;
  }

  return null;
}

export function isActionableTaskState(state: AgentTeamTaskDisplayState) {
  return state.kind === "needs_attention" || state.kind === "failed";
}

export function nextStepForWorkbench({
  activeBundle,
  blockedExplanation,
  changedFiles,
  evidenceItems,
  isChineseUi,
  readyTasksCount,
  runningTasksCount,
  taskDisplayStates,
  tasks,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  blockedExplanation: string | null;
  changedFiles: string[];
  evidenceItems: string[];
  isChineseUi: boolean;
  readyTasksCount: number;
  runningTasksCount: number;
  taskDisplayStates: AgentTeamTaskDisplayState[];
  tasks: AgentTeamTask[];
}) {
  if (!tasks.length) {
    return {
      label: isChineseUi ? "先生成动态协作方案" : "Generate the dynamic collaboration plan first",
      help: isChineseUi
        ? "把 Mission 目标拆成有依赖关系、验收标准和运行边界的任务。"
        : "Split the mission goal into tasks with dependencies, acceptance criteria, and run boundaries.",
    };
  }

  if (runningTasksCount) {
    return {
      label: isChineseUi ? "Mission 正在运行，等待任务回传依据" : "Mission is running; wait for task evidence",
      help: isChineseUi
        ? "运行中会轻量轮询当前 Mission，任务完成后依据和需要注意的事项会回到右侧。"
        : "The current mission is lightly polled while running; evidence and risks appear on the right.",
    };
  }

  if (taskDisplayStates.some(isActionableTaskState)) {
    return {
      label: isChineseUi ? "先处理需要注意的任务" : "Resolve tasks that need attention first",
      help:
        blockedExplanation ??
        (isChineseUi
          ? "查看任务详情中的错误和注意事项，然后再继续推进。"
          : "Review task errors and notes before continuing."),
    };
  }

  if (readyTasksCount) {
    return {
      label: isChineseUi ? "运行 Mission，自动推进可执行任务" : "Run the mission and advance ready tasks",
      help: isChineseUi
        ? "系统会按依赖顺序推进任务；未准备好的任务会继续等待前置任务。"
        : "The system advances tasks in dependency order; tasks that are not ready keep waiting for prerequisites.",
    };
  }

  if (finalAnswerStatusForBundle(activeBundle) === "placeholder") {
    return {
      label: isChineseUi ? "当前是模拟执行，需真实运行后再交付" : "This is simulated; run for real before delivery",
      help: isChineseUi
        ? "模拟执行只说明流程走通，没有生成面向用户目标的最终答案。"
        : "A simulated run only proves the workflow; it does not answer the user's goal.",
    };
  }

  if (activeBundle?.recommended_next_action === "request_changes") {
    return {
      label: isChineseUi ? "交付前先处理风险和修改项" : "Resolve risks and requested changes before delivery",
      help: isChineseUi
        ? "最终结果已经生成，但仍有风险或待处理事项；先处理这些问题再交付。"
        : "The final result exists, but risks or requested changes remain. Resolve them before delivery.",
    };
  }

  if (activeBundle) {
    return {
      label: isChineseUi ? "查看最终结果并决定下一步" : "Review the final result and decide the next action",
      help: isChineseUi
        ? "检查最终结果里的改动、依据、风险和开放问题，再决定交付、拆分跟进或放弃。"
        : "Review changes, evidence, risks, and open questions before choosing delivery, follow-up, or discard.",
    };
  }

  if (evidenceItems.length || changedFiles.length) {
    return {
      label: isChineseUi ? "已有产出后，生成最终结果" : "Generate a final result once outputs are ready",
      help: isChineseUi
        ? "把产出、风险和验证依据收束成用户可读的结果。"
        : "Collect outputs, risks, and evidence into a user-facing result.",
    };
  }

  return {
    label: isChineseUi ? "检查任务依赖，必要时打开分支线程处理待办事项" : "Check dependencies and use branch threads for follow-up",
    help: isChineseUi
      ? "分支线程是辅助入口；主流程仍在这里生成方案、运行 Mission 和生成最终结果。"
      : "Branch threads are supporting links; the main flow stays here for planning, running the mission, and final results.",
  };
}
