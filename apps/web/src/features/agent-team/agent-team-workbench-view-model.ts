import { useCallback, useEffect, useMemo, useRef, useState, type SetStateAction } from "react";

import {
  deriveTaskDisplayStates,
  isFallbackPlan,
  isTaskDone,
  isTaskQueued,
  isTaskReady,
  isTaskRunning,
  normalizeMergeBundle,
  normalizeSessionView,
  planningSourceLabel,
  statusLabel,
  titleFromGoal,
  uniqueNonEmptyStrings,
  type AgentTeamTaskDisplayState,
} from "./agent-team-workbench-utils";
import type { AgentTeamMergeBundle, AgentTeamSession, AgentTeamSessionView, AgentTeamTask } from "./types";

export type AgentTeamWorkbenchPhaseKey = "plan" | "execute" | "verify" | "synthesize";

export interface AgentTeamWorkbenchPhaseGroup {
  key: AgentTeamWorkbenchPhaseKey;
  label: string;
  help: string;
  tasks: AgentTeamTask[];
  completedCount: number;
  blockedCount: number;
  readyCount: number;
}

export type AgentTeamWorkbenchPhaseMapStatus = "empty" | "waiting" | "ready" | "running" | "attention" | "complete";

export interface AgentTeamWorkbenchPhaseMapItem extends AgentTeamWorkbenchPhaseGroup {
  taskIds: string[];
  status: AgentTeamWorkbenchPhaseMapStatus;
  progressLabel: string;
  isActive: boolean;
  isComplete: boolean;
  hasRecommendedTask: boolean;
  selectedTaskId: string | null;
  recommendedTaskId: string | null;
}

export interface AgentTeamWorkbenchMissionHeaderState {
  sessionId: string | null;
  rootThreadId: string | null;
  title: string;
  goal: string;
  status: string;
  statusLabel: string;
  stageLabel: string;
  stageHelp?: string;
  tone: string;
  progressLabel: string;
  progressPercent: number;
  planningSource: string;
  fallbackPlan: boolean;
}

export type AgentTeamWorkbenchFinalResultStateKind = "missing" | "ready" | "placeholder" | "blocked" | "error";

export interface AgentTeamWorkbenchFinalResultState {
  kind: AgentTeamWorkbenchFinalResultStateKind;
  label: string;
  help: string;
  deliverable: boolean;
  summary: string;
  warnings: string[];
}

export interface AgentTeamWorkbenchFinalPreviewState extends AgentTeamWorkbenchFinalResultState {
  hasBundle: boolean;
  canApprove: boolean;
  evidenceItems: string[];
  riskItems: string[];
  nextActionLabel: string;
}

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

export function useAgentTeamWorkbenchViewModel({
  isChineseUi,
  mergeProposalData,
  sessionData,
}: {
  isChineseUi: boolean;
  mergeProposalData: AgentTeamMergeBundle | AgentTeamSessionView | undefined;
  sessionData: AgentTeamSession | AgentTeamSessionView | undefined;
}) {
  const view = normalizeSessionView(sessionData);
  const tasks = view?.tasks ?? [];
  const [focusState, setFocusState] = useState<{
    manualFocusTaskId: string | null;
    selectedTaskId: string | null;
  }>({
    manualFocusTaskId: null,
    selectedTaskId: null,
  });
  const { manualFocusTaskId, selectedTaskId } = focusState;
  const manualFocusStateKindRef = useRef<AgentTeamTaskDisplayState["kind"] | null>(null);
  const setSelectedTaskId = useCallback((nextTaskId: SetStateAction<string | null>) => {
    setFocusState((currentFocusState) => {
      const resolvedTaskId =
        typeof nextTaskId === "function" ? nextTaskId(currentFocusState.selectedTaskId) : nextTaskId;
      return {
        manualFocusTaskId: resolvedTaskId,
        selectedTaskId: resolvedTaskId,
      };
    });
  }, []);
  const pendingBundle = normalizeMergeBundle(mergeProposalData);
  const activeBundle = pendingBundle ?? view?.merge_bundle ?? null;
  const changedFiles = uniqueNonEmptyStrings(tasks.flatMap((task) => task.changed_files ?? []));
  const outputArtifactIds = uniqueNonEmptyStrings(tasks.flatMap((task) => task.output_artifact_ids ?? []));
  const evidenceItems = uniqueNonEmptyStrings([
    ...(view?.evidence ?? []),
    ...outputArtifactIds,
    ...(view?.artifacts ?? []).map((artifact) => artifact.summary ?? artifact.title ?? artifact.artifact_id),
    ...tasks.map((task) => task.verification_summary),
    ...(activeBundle?.test_evidence ?? []),
  ]);
  const riskItems = uniqueNonEmptyStrings([
    ...(view?.risks ?? []),
    ...tasks.flatMap((task) => task.risk_notes ?? []),
    ...(activeBundle?.risk_items ?? []),
  ]);
  const readyTasks = tasks.filter((task) => isTaskReady(task, tasks));
  const runningTasks = tasks.filter(isTaskRunning);
  const queuedTasks = tasks.filter(isTaskQueued);
  const doneTasks = tasks.filter(isTaskDone);
  const taskDisplayStates = deriveTaskDisplayStates(tasks, isChineseUi);
  const taskDisplayState = taskDisplayStates.reduce<Record<string, AgentTeamTaskDisplayState>>((states, state) => {
    states[state.taskId] = state;
    return states;
  }, {});
  const needsAttentionTaskStates = taskDisplayStates.filter(isActionableTaskState);
  const waitingDependencyTaskStates = taskDisplayStates.filter((state) => state.kind === "waiting_dependency");
  const recommendedTaskState = useMemo(
    () => recommendedTaskStateForSelection(taskDisplayStates, tasks),
    [taskDisplayStates, tasks],
  );
  const recommendedTaskId = recommendedTaskState?.taskId ?? null;
  const selectedTaskState = selectedTaskId ? taskDisplayState[selectedTaskId] ?? null : null;

  useEffect(() => {
    if (!selectedTaskId) {
      manualFocusStateKindRef.current = null;
      return;
    }
    const selectedTaskExists = tasks.some((task) => task.task_id === selectedTaskId);
    if (!selectedTaskExists) {
      setFocusState({
        manualFocusTaskId: null,
        selectedTaskId: recommendedTaskId,
      });
      manualFocusStateKindRef.current = null;
      return;
    }
    const isManualSelectedTask = manualFocusTaskId === selectedTaskId;
    const selectedTaskKind = selectedTaskState?.kind ?? null;
    const didManualTaskJustComplete =
      isManualSelectedTask &&
      selectedTaskKind === "completed" &&
      manualFocusStateKindRef.current !== null &&
      manualFocusStateKindRef.current !== "completed";
    if (
      didManualTaskJustComplete &&
      shouldAutoAdvanceFocus({
        recommendedTaskId,
        recommendedTaskState,
        selectedTaskId,
        selectedTaskState,
      })
    ) {
      setFocusState({
        manualFocusTaskId: null,
        selectedTaskId: recommendedTaskId,
      });
      manualFocusStateKindRef.current = null;
      return;
    }
    manualFocusStateKindRef.current = isManualSelectedTask ? selectedTaskKind : null;
  }, [manualFocusTaskId, recommendedTaskId, recommendedTaskState, selectedTaskId, selectedTaskState, tasks]);

  const selectedTask = useMemo(() => {
    if (!tasks.length) return null;
    const explicitTask = selectedTaskId ? tasks.find((task) => task.task_id === selectedTaskId) : null;
    if (explicitTask) return explicitTask;
    return tasks.find((task) => task.task_id === recommendedTaskId) ?? tasks[0];
  }, [recommendedTaskId, selectedTaskId, tasks]);
  const selectedTaskFocusState = selectedTask ? taskDisplayState[selectedTask.task_id] ?? null : null;
  const session = view?.session ?? null;
  const displayTitle = session?.title && session.title !== session.goal ? session.title : titleFromGoal(session?.goal ?? "");
  const fallbackPlan = isFallbackPlan(session, tasks);
  const planningMetadata = {
    generatedAt: session?.plan_generated_at ?? session?.updated_at ?? null,
    model: session?.planner_model_id?.trim() || (isChineseUi ? "未记录" : "Not recorded"),
    source: planningSourceLabel(session?.planning_source ?? tasks[0]?.plan_source, isChineseUi),
    taskCount: tasks.length,
  };
  const missionProgress = {
    total: tasks.length,
    done: doneTasks.length,
    completed: doneTasks.length,
    running: runningTasks.length,
    queued: queuedTasks.length,
    blocked: needsAttentionTaskStates.length,
    needsAttention: needsAttentionTaskStates.length,
    ready: readyTasks.length,
    waitingDependencies: waitingDependencyTaskStates.length,
    percent: tasks.length ? Math.round((doneTasks.length / tasks.length) * 100) : 0,
  };
  const allTasksComplete =
    tasks.length > 0 &&
    doneTasks.length >= tasks.length &&
    !runningTasks.length &&
    !queuedTasks.length &&
    !needsAttentionTaskStates.length;
  const canGenerateResult = Boolean(activeBundle) || allTasksComplete;
  const blockedExplanation = blockedExplanationForWorkbench({
    isChineseUi,
    taskDisplayStates,
  });
  const missionStage = missionStageForWorkbench({
    activeBundle,
    blockedExplanation,
    doneTasksCount: doneTasks.length,
    isChineseUi,
    readyTasksCount: readyTasks.length,
    queuedTasksCount: queuedTasks.length,
    runningTasksCount: runningTasks.length,
    taskDisplayStates,
    tasks,
  });
  const primaryAction = primaryActionForWorkbench({
    activeBundle,
    blockedExplanation,
    doneTasksCount: doneTasks.length,
    isChineseUi,
    readyTasksCount: readyTasks.length,
    queuedTasksCount: queuedTasks.length,
    runningTasksCount: runningTasks.length,
    taskDisplayStates,
    tasks,
  });
  const missionHeaderState = missionHeaderStateForWorkbench({
    displayTitle,
    fallbackPlan,
    isChineseUi,
    missionProgress,
    missionStage,
    planningMetadata,
    session,
  });
  const userFacingResult = userFacingResultForWorkbench({
    activeBundle,
    changedFiles,
    evidenceItems,
    isChineseUi,
    riskItems,
  });
  const advancedMeta = {
    planning: {
      ...planningMetadata,
      rationale: session?.planning_rationale ?? view?.planning?.rationale ?? null,
      planHash: session?.plan_hash ?? view?.planning?.plan_hash ?? null,
      error: session?.planning_error ?? view?.planning?.error ?? null,
    },
    dag: view?.dag ?? null,
    rawEvidence: {
      evidenceItems,
      executionEvidence: activeBundle?.execution_evidence ?? [],
      testEvidence: activeBundle?.test_evidence ?? [],
    },
    changedFiles: uniqueNonEmptyStrings([...(activeBundle?.changed_files ?? []), ...changedFiles]),
    artifacts: view?.artifacts ?? [],
    openQuestions: activeBundle?.open_questions ?? [],
  };
  const nextStepHint = nextStepForWorkbench({
    activeBundle,
    blockedExplanation,
    changedFiles,
    evidenceItems,
    isChineseUi,
    readyTasksCount: readyTasks.length,
    runningTasksCount: runningTasks.length,
    taskDisplayStates,
    tasks,
  });
  const isPlanReview = isPlanReviewState({
    activeBundle,
    taskDisplayStates,
    tasks,
  });
  const phaseGroups = buildPhaseGroups(tasks, taskDisplayState, isChineseUi);
  const phaseMapItems = buildPhaseMapItems({
    isChineseUi,
    phaseGroups,
    recommendedTaskId,
    selectedTaskId: selectedTask?.task_id ?? null,
  });
  const focusReason = recommendedTaskReasonForSelection({
    isChineseUi,
    isManualFocus: Boolean(manualFocusTaskId && selectedTask?.task_id === manualFocusTaskId),
    recommendedTaskId,
    selectedTask,
    taskDisplayState,
    tasks,
  });
  const finalPreviewState = finalPreviewStateForWorkbench({
    activeBundle,
    evidenceItems,
    isChineseUi,
    riskItems,
  });
  const decisionDockState = decisionDockStateForWorkbench({
    blockedExplanation,
    canGenerateResult,
    finalPreviewState,
    focusReason,
    nextStepHint,
    primaryAction,
    recommendedTaskId,
    riskItems,
    selectedTaskState: selectedTaskFocusState,
  });
  const finalResultState = finalPreviewState;
  const recommendedTaskReason = focusReason;

  return {
    activeBundle,
    changedFiles,
    displayTitle,
    evidenceItems,
    fallbackPlan,
    advancedMeta,
    blockedExplanation,
    decisionDockState,
    finalPreviewState,
    focusReason,
    missionHeaderState,
    missionStage,
    missionProgress,
    nextStepHint,
    isPlanReview,
    pendingBundle,
    phaseMapItems,
    phaseGroups,
    planningMetadata,
    primaryAction,
    queuedTasks,
    readyTasks,
    recommendedTaskId,
    riskItems,
    runningTasks,
    selectedTask,
    setSelectedTaskId,
    recommendedTaskReason,
    taskDisplayState,
    taskDisplayStates,
    tasks,
    userFacingResult,
    view,
    nextStep: nextStepHint,
    finalResultState,
  };
}

function missionHeaderStateForWorkbench({
  displayTitle,
  fallbackPlan,
  isChineseUi,
  missionProgress,
  missionStage,
  planningMetadata,
  session,
}: {
  displayTitle: string;
  fallbackPlan: boolean;
  isChineseUi: boolean;
  missionProgress: {
    done: number;
    percent: number;
    total: number;
  };
  missionStage: {
    help?: string;
    label: string;
    tone?: string;
  };
  planningMetadata: {
    source: string;
  };
  session: AgentTeamSession | null;
}): AgentTeamWorkbenchMissionHeaderState {
  const sessionTitle = displayTitle || session?.session_id || "Agent Team Mission";
  return {
    sessionId: session?.session_id ?? null,
    rootThreadId: session?.root_thread_id ?? null,
    title: sessionTitle,
    goal: session?.goal ?? "",
    status: session?.status ?? "pending",
    statusLabel: statusLabel(session?.status ?? "pending", isChineseUi),
    stageLabel: missionStage.label,
    stageHelp: missionStage.help,
    tone: missionStage.tone ?? "neutral",
    progressLabel: `${missionProgress.done}/${missionProgress.total}`,
    progressPercent: missionProgress.percent,
    planningSource: planningMetadata.source,
    fallbackPlan,
  };
}

function shouldAutoAdvanceFocus({
  recommendedTaskId,
  recommendedTaskState,
  selectedTaskId,
  selectedTaskState,
}: {
  recommendedTaskId: string | null;
  recommendedTaskState: AgentTeamTaskDisplayState | undefined;
  selectedTaskId: string;
  selectedTaskState: AgentTeamTaskDisplayState | null;
}) {
  if (!recommendedTaskId || recommendedTaskId === selectedTaskId) return false;
  if (!recommendedTaskState || selectedTaskState?.kind !== "completed") return false;
  return focusPriorityForTaskState(recommendedTaskState) < focusPriorityForTaskState(selectedTaskState);
}

function focusPriorityForTaskState(state: AgentTeamTaskDisplayState) {
  const priorities: Record<AgentTeamTaskDisplayState["kind"], number> = {
    failed: 0,
    needs_attention: 0,
    running: 1,
    queued: 1,
    ready: 2,
    waiting_dependency: 4,
    pending: 4,
    completed: 5,
  };
  return priorities[state.kind] ?? 9;
}

function recommendedTaskStateForSelection(
  taskDisplayStates: AgentTeamTaskDisplayState[],
  tasks: AgentTeamTask[],
) {
  return (
    taskDisplayStates.find((state) => state.kind === "failed" || state.kind === "needs_attention") ??
    taskDisplayStates.find((state) => state.kind === "running" || state.kind === "queued") ??
    taskDisplayStates.find((state) => state.kind === "ready") ??
    [...taskDisplayStates]
      .filter((state) => state.kind === "completed")
      .sort((left, right) => timestampForTaskId(right.taskId, tasks) - timestampForTaskId(left.taskId, tasks))[0] ??
    taskDisplayStates[0]
  );
}

function timestampForTaskId(taskId: string, tasks: AgentTeamTask[]) {
  const task = tasks.find((item) => item.task_id === taskId);
  const timestamp = Date.parse(task?.finished_at ?? task?.updated_at ?? task?.created_at ?? "");
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function isPlanReviewState({
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

function buildPhaseGroups(
  tasks: AgentTeamTask[],
  taskDisplayState: Record<string, AgentTeamTaskDisplayState>,
  isChineseUi: boolean,
): AgentTeamWorkbenchPhaseGroup[] {
  const groups: AgentTeamWorkbenchPhaseGroup[] = [
    {
      key: "plan",
      label: isChineseUi ? "Discover" : "Discover",
      help: isChineseUi ? "识别目标、交付物和依赖边界。" : "Identify the goal, deliverables, and dependency boundaries.",
      tasks: [],
      completedCount: 0,
      blockedCount: 0,
      readyCount: 0,
    },
    {
      key: "execute",
      label: isChineseUi ? "Build" : "Build",
      help: isChineseUi ? "产出可交付改动、材料或结论。" : "Produce deliverable changes, artifacts, or findings.",
      tasks: [],
      completedCount: 0,
      blockedCount: 0,
      readyCount: 0,
    },
    {
      key: "verify",
      label: isChineseUi ? "Validate" : "Validate",
      help: isChineseUi ? "补齐测试、审查和验收证据。" : "Collect tests, review notes, and acceptance evidence.",
      tasks: [],
      completedCount: 0,
      blockedCount: 0,
      readyCount: 0,
    },
    {
      key: "synthesize",
      label: isChineseUi ? "Deliver" : "Deliver",
      help: isChineseUi ? "收束最终回答、风险和开放问题。" : "Synthesize final answer, risks, and open questions.",
      tasks: [],
      completedCount: 0,
      blockedCount: 0,
      readyCount: 0,
    },
  ];
  const byKey = new Map(groups.map((group) => [group.key, group]));
  for (const task of tasks) {
    const group = byKey.get(phaseKeyForTask(task)) ?? groups[1];
    const state = taskDisplayState[task.task_id];
    group.tasks.push(task);
    if (state?.kind === "completed") group.completedCount += 1;
    if (state?.kind === "failed" || state?.kind === "needs_attention") group.blockedCount += 1;
    if (state?.kind === "ready") group.readyCount += 1;
  }
  return groups;
}

function buildPhaseMapItems({
  isChineseUi,
  phaseGroups,
  recommendedTaskId,
  selectedTaskId,
}: {
  isChineseUi: boolean;
  phaseGroups: AgentTeamWorkbenchPhaseGroup[];
  recommendedTaskId: string | null;
  selectedTaskId: string | null;
}): AgentTeamWorkbenchPhaseMapItem[] {
  return phaseGroups.map((group) => {
    const taskIds = group.tasks.map((task) => task.task_id);
    const hasRecommendedTask = Boolean(recommendedTaskId && taskIds.includes(recommendedTaskId));
    const isActive = Boolean((selectedTaskId && taskIds.includes(selectedTaskId)) || hasRecommendedTask);
    const isComplete = Boolean(group.tasks.length && group.completedCount >= group.tasks.length);
    return {
      ...group,
      taskIds,
      status: phaseMapStatusForGroup(group),
      progressLabel: group.tasks.length
        ? `${group.completedCount}/${group.tasks.length}`
        : isChineseUi
          ? "暂无任务"
          : "No tasks",
      isActive,
      isComplete,
      hasRecommendedTask,
      selectedTaskId: selectedTaskId && taskIds.includes(selectedTaskId) ? selectedTaskId : null,
      recommendedTaskId: hasRecommendedTask ? recommendedTaskId : null,
    };
  });
}

function phaseMapStatusForGroup(group: AgentTeamWorkbenchPhaseGroup): AgentTeamWorkbenchPhaseMapStatus {
  if (!group.tasks.length) return "empty";
  if (group.blockedCount) return "attention";
  if (group.tasks.some((task) => isTaskRunning(task) || isTaskQueued(task))) return "running";
  if (group.readyCount) return "ready";
  if (group.completedCount >= group.tasks.length) return "complete";
  return "waiting";
}

function phaseKeyForTask(task: AgentTeamTask): AgentTeamWorkbenchPhaseKey {
  const descriptor = [task.role, task.task_type, task.title, task.goal].join(" ").toLowerCase();
  if (/(plan|planner|architect|research|design|拆解|规划|方案)/.test(descriptor)) return "plan";
  if (/(test|verify|verification|review|qa|risk|审查|验证|测试|风险)/.test(descriptor)) return "verify";
  if (/(synth|merge|writer|summary|final|handoff|汇总|收束|交付|总结)/.test(descriptor)) return "synthesize";
  return "execute";
}

function recommendedTaskReasonForSelection({
  isChineseUi,
  isManualFocus,
  recommendedTaskId,
  selectedTask,
  taskDisplayState,
  tasks,
}: {
  isChineseUi: boolean;
  isManualFocus: boolean;
  recommendedTaskId: string | null;
  selectedTask: AgentTeamTask | null;
  taskDisplayState: Record<string, AgentTeamTaskDisplayState>;
  tasks: AgentTeamTask[];
}) {
  if (!selectedTask) {
    return isChineseUi ? "还没有任务，先生成协作方案。" : "No tasks yet; generate the collaboration plan first.";
  }
  const state = taskDisplayState[selectedTask.task_id];
  if (isManualFocus && recommendedTaskId && recommendedTaskId !== selectedTask.task_id && state?.kind !== "completed") {
    return isChineseUi
      ? "你手动选择了这个任务，Cockpit 会保持焦点；等它完成且出现更需要关注的推荐任务时再自动推进。"
      : "You manually focused this task, so Cockpit will stay here until it completes and a more important recommended task appears.";
  }
  if (state?.kind === "failed" || state?.kind === "needs_attention") {
    return isChineseUi
      ? "失败或需要处理的任务会优先进入焦点，避免继续推进时掩盖风险。"
      : "Failed or blocked work is focused first so the mission does not advance over hidden risk.";
  }
  if (state?.kind === "running" || state?.kind === "queued") {
    return isChineseUi
      ? "当前正在执行或排队，最值得关注它的回传状态。"
      : "This task is running or queued, so its return state matters most right now.";
  }
  if (state?.kind === "ready") {
    return isChineseUi
      ? "它的依赖已经满足，是下一批可以启动的任务。"
      : "Its dependencies are satisfied, making it part of the next runnable batch.";
  }
  if (state?.kind === "completed") {
    return isChineseUi
      ? "当前没有更紧急事项，先查看最近完成产出是否可用于最终汇总。"
      : "No more urgent item is available, so review completed output for final synthesis.";
  }
  const dependencyCount = state?.incompleteDependencies.length ?? selectedTask.dependencies?.length ?? 0;
  if (dependencyCount) {
    return isChineseUi
      ? `它还在等待 ${dependencyCount} 个前置任务完成。`
      : `It is waiting for ${dependencyCount} prerequisite task${dependencyCount === 1 ? "" : "s"}.`;
  }
  return tasks.length
    ? isChineseUi
      ? "这是当前 Mission 的第一个可观察任务。"
      : "This is the first task available for inspection in the mission."
    : isChineseUi
      ? "还没有任务。"
      : "No task is available.";
}

function decisionDockStateForWorkbench({
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

function finalPreviewStateForWorkbench({
  activeBundle,
  evidenceItems,
  isChineseUi,
  riskItems,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  evidenceItems: string[];
  isChineseUi: boolean;
  riskItems: string[];
}): AgentTeamWorkbenchFinalPreviewState {
  const resultState = finalResultStateForWorkbench(activeBundle, isChineseUi);
  const bundleEvidence = uniqueNonEmptyStrings([
    ...(activeBundle?.key_findings ?? []),
    ...(activeBundle?.test_evidence ?? []),
    ...(activeBundle?.changed_files ?? []),
    ...evidenceItems,
  ]);
  const bundleRisks = uniqueNonEmptyStrings([
    ...(activeBundle?.risk_items ?? []),
    ...(activeBundle?.open_questions ?? []).map((question) =>
      isChineseUi ? `待确认：${question}` : `Open question: ${question}`,
    ),
    ...riskItems,
  ]);
  return {
    ...resultState,
    hasBundle: Boolean(activeBundle),
    canApprove: resultState.deliverable,
    evidenceItems: bundleEvidence,
    riskItems: bundleRisks,
    nextActionLabel: nextActionLabelForBundle(activeBundle, isChineseUi),
  };
}

function finalResultStateForWorkbench(
  activeBundle: AgentTeamMergeBundle | null,
  isChineseUi: boolean,
): AgentTeamWorkbenchFinalResultState {
  if (!activeBundle) {
    return {
      kind: "missing",
      label: isChineseUi ? "尚未生成" : "Missing",
      help: isChineseUi ? "任务完成后再生成最终结果。" : "Generate the final result after task outputs are ready.",
      deliverable: false,
      summary: isChineseUi ? "Final Preview 尚未生成。" : "Final Preview has not been generated.",
      warnings: [],
    };
  }
  const explicitStatus = finalAnswerStatusForBundle(activeBundle);
  const isSimulated = explicitStatus === "placeholder" || isBundleSimulated(activeBundle);
  const hasSynthesisError = explicitStatus === "error";
  const isBlocked = explicitStatus === "blocked" || activeBundle.recommended_next_action === "request_changes";
  const isDeliverable =
    !isSimulated &&
    !hasSynthesisError &&
    !isBlocked &&
    (explicitStatus === "ready" || activeBundle.recommended_next_action === "merge");
  const kind: AgentTeamWorkbenchFinalResultStateKind = isSimulated
    ? "placeholder"
    : hasSynthesisError
      ? "error"
      : isBlocked
        ? "blocked"
        : isDeliverable
          ? "ready"
          : "blocked";
  const warnings = uniqueNonEmptyStrings([
    ...(activeBundle.final_answer_warnings ?? []),
    isSimulated
      ? isChineseUi
        ? "模拟或 placeholder 结果不可交付。"
        : "Simulated or placeholder output is not deliverable."
      : null,
    hasSynthesisError
      ? isChineseUi
        ? "最终结果生成遇到错误。"
        : "Final synthesis returned an error."
      : null,
    isBlocked
      ? isChineseUi
        ? "仍有阻塞或修改项，不能包装成完成态。"
        : "Blocked or requested-change output cannot be marked complete."
      : null,
  ]);
  return {
    kind,
    label: isDeliverable ? (isChineseUi ? "可交付" : "Deliverable") : isChineseUi ? "不可交付" : "Not deliverable",
    help: isDeliverable
      ? isChineseUi
        ? "最终结果已准备好，可以确认完成。"
        : "The final result is ready to approve."
      : isChineseUi
        ? "Final Preview 只能展示为待处理状态，不能确认完成。"
        : "Final Preview must remain pending and cannot be approved.",
    deliverable: isDeliverable,
    summary:
      activeBundle.final_answer ||
      activeBundle.summary ||
      (isChineseUi ? "最终结果为空。" : "Final result is empty."),
    warnings,
  };
}

function primaryActionForWorkbench({
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

function missionStageForWorkbench({
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

function blockedExplanationForWorkbench({
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

function isActionableTaskState(state: AgentTeamTaskDisplayState) {
  return state.kind === "needs_attention" || state.kind === "failed";
}

function userFacingResultForWorkbench({
  activeBundle,
  changedFiles,
  evidenceItems,
  isChineseUi,
  riskItems,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  changedFiles: string[];
  evidenceItems: string[];
  isChineseUi: boolean;
  riskItems: string[];
}) {
  const bundleEvidence = uniqueNonEmptyStrings([
    ...(activeBundle?.key_findings ?? []),
    ...(activeBundle?.test_evidence ?? []),
    ...(activeBundle?.changed_files ?? []),
    ...evidenceItems,
  ]);
  const bundleRisks = uniqueNonEmptyStrings([
    ...(activeBundle?.risk_items ?? []),
    ...(activeBundle?.open_questions ?? []).map((question) =>
      isChineseUi ? `待确认：${question}` : `Open question: ${question}`,
    ),
    ...riskItems,
  ]);

  return {
    summary:
      activeBundle?.final_answer ??
      activeBundle?.summary ??
      (isChineseUi
        ? "最终结果尚未生成。完成任务后，可以把产出、依据和风险汇总给用户。"
        : "The final result has not been generated yet. Once tasks finish, outputs, evidence, and risks can be summarized for the user."),
    evidence: bundleEvidence.length
      ? bundleEvidence
      : uniqueNonEmptyStrings([
          changedFiles.length
            ? isChineseUi
              ? `涉及 ${changedFiles.length} 个变更文件`
              : `${changedFiles.length} changed files`
            : null,
        ]),
    risks: bundleRisks.length
      ? bundleRisks
      : [isChineseUi ? "暂未发现明确风险。" : "No explicit risks have been reported yet."],
    nextActionLabel: nextActionLabelForBundle(activeBundle, isChineseUi),
  };
}

function nextActionLabelForBundle(bundle: AgentTeamMergeBundle | null, isChineseUi: boolean) {
  const finalStatus = finalAnswerStatusForBundle(bundle);
  if (finalStatus === "placeholder") return isChineseUi ? "模拟执行，需真实运行" : "Simulated; run for real";
  if (finalStatus === "blocked") return isChineseUi ? "先补齐任务产出" : "Complete missing outputs first";
  if (finalStatus === "error") return isChineseUi ? "先处理生成错误" : "Resolve synthesis error first";
  if (finalStatus === "ready") return isChineseUi ? "可交付" : "Deliverable";
  const action = bundle?.recommended_next_action;
  if (action === "merge") return isChineseUi ? "可交付" : "Deliverable";
  if (action === "request_changes") return isChineseUi ? "先处理修改项" : "Request changes first";
  if (action === "split_followup") return isChineseUi ? "拆分后续任务" : "Split follow-up tasks";
  if (action === "discard") return isChineseUi ? "放弃本次结果" : "Discard this result";
  return isChineseUi ? "生成最终结果" : "Generate final result";
}

function nextStepForWorkbench({
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

function finalAnswerStatusForBundle(bundle: AgentTeamMergeBundle | null) {
  const explicit = bundle?.final_answer_status?.trim();
  if (explicit) return explicit;
  if (!bundle) return null;
  return isBundleSimulated(bundle) ? "placeholder" : null;
}

function isBundleSimulated(bundle: AgentTeamMergeBundle) {
  return [
    bundle.summary,
    bundle.final_answer,
    ...(bundle.key_findings ?? []),
    ...(bundle.test_evidence ?? []),
    ...(bundle.risk_items ?? []),
    ...(bundle.open_questions ?? []),
  ].some((item) => Boolean(item && /(?:^|\b)(fake delegated|delegated fake run|run-|artifact-)/i.test(item.trim())));
}
