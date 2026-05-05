import { useMemo, useState } from "react";

import {
  deriveTaskDisplayStates,
  isFallbackPlan,
  isTaskDone,
  isTaskReady,
  isTaskRunning,
  normalizeMergeBundle,
  normalizeSessionView,
  planningSourceLabel,
  titleFromGoal,
  uniqueNonEmptyStrings,
  type AgentTeamTaskDisplayState,
} from "./agent-team-workbench-utils";
import type { AgentTeamMergeBundle, AgentTeamSession, AgentTeamSessionView, AgentTeamTask } from "./types";

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
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const selectedTask = useMemo(() => {
    if (!tasks.length) return null;
    return tasks.find((task) => task.task_id === selectedTaskId) ?? tasks[0];
  }, [selectedTaskId, tasks]);
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
  const doneTasks = tasks.filter(isTaskDone);
  const taskDisplayStates = deriveTaskDisplayStates(tasks, isChineseUi);
  const taskDisplayState = taskDisplayStates.reduce<Record<string, AgentTeamTaskDisplayState>>((states, state) => {
    states[state.taskId] = state;
    return states;
  }, {});
  const needsAttentionTaskStates = taskDisplayStates.filter(isActionableTaskState);
  const waitingDependencyTaskStates = taskDisplayStates.filter((state) => state.kind === "waiting_dependency");
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
    blocked: needsAttentionTaskStates.length,
    needsAttention: needsAttentionTaskStates.length,
    ready: readyTasks.length,
    waitingDependencies: waitingDependencyTaskStates.length,
    percent: tasks.length ? Math.round((doneTasks.length / tasks.length) * 100) : 0,
  };
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
    runningTasksCount: runningTasks.length,
    taskDisplayStates,
    tasks,
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

  return {
    activeBundle,
    changedFiles,
    displayTitle,
    evidenceItems,
    fallbackPlan,
    advancedMeta,
    blockedExplanation,
    missionStage,
    missionProgress,
    nextStepHint,
    pendingBundle,
    planningMetadata,
    primaryAction,
    readyTasks,
    riskItems,
    runningTasks,
    selectedTask,
    setSelectedTaskId,
    taskDisplayState,
    taskDisplayStates,
    tasks,
    userFacingResult,
    view,
    nextStep: nextStepHint,
  };
}

function primaryActionForWorkbench({
  activeBundle,
  blockedExplanation,
  doneTasksCount,
  isChineseUi,
  readyTasksCount,
  runningTasksCount,
  taskDisplayStates,
  tasks,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  blockedExplanation: string | null;
  doneTasksCount: number;
  isChineseUi: boolean;
  readyTasksCount: number;
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

  if (runningTasksCount) {
    return {
      kind: "running",
      label: isChineseUi ? "执行中..." : "Running...",
      help: isChineseUi
        ? "Mission 正在执行，等待任务回传产出、依据和需要注意的事项。"
        : "The mission is running; wait for task outputs, evidence, and risks.",
      disabledReason: isChineseUi ? "当前已有任务执行中" : "A task is already running",
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
  runningTasksCount,
  taskDisplayStates,
  tasks,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  blockedExplanation: string | null;
  doneTasksCount: number;
  isChineseUi: boolean;
  readyTasksCount: number;
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

  if (runningTasksCount) {
    return {
      kind: "running",
      label: isChineseUi ? "执行中" : "Running",
      help: isChineseUi ? "任务正在执行，等待产出回传。" : "Tasks are running; wait for outputs to return.",
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
