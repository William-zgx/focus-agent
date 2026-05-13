import { statusLabel, uniqueNonEmptyStrings } from "./agent-team-workbench-utils";
import type { AgentTeamMergeBundle, AgentTeamSession, AgentTeamSessionView, AgentTeamTask } from "./types";

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

export interface AgentTeamWorkbenchEvidenceRiskState {
  changedFiles: string[];
  evidenceItems: string[];
  riskItems: string[];
}

export interface AgentTeamWorkbenchMissionProgressState {
  total: number;
  done: number;
  completed: number;
  running: number;
  queued: number;
  blocked: number;
  needsAttention: number;
  ready: number;
  waitingDependencies: number;
  percent: number;
}

export function deriveWorkbenchEvidenceRiskState({
  activeBundle,
  tasks,
  view,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  tasks: AgentTeamTask[];
  view: AgentTeamSessionView | null;
}): AgentTeamWorkbenchEvidenceRiskState {
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

  return {
    changedFiles,
    evidenceItems,
    riskItems,
  };
}

export function missionProgressStateForWorkbench({
  doneTasksCount,
  needsAttentionCount,
  queuedTasksCount,
  readyTasksCount,
  runningTasksCount,
  taskCount,
  waitingDependencyCount,
}: {
  doneTasksCount: number;
  needsAttentionCount: number;
  queuedTasksCount: number;
  readyTasksCount: number;
  runningTasksCount: number;
  taskCount: number;
  waitingDependencyCount: number;
}): AgentTeamWorkbenchMissionProgressState {
  return {
    total: taskCount,
    done: doneTasksCount,
    completed: doneTasksCount,
    running: runningTasksCount,
    queued: queuedTasksCount,
    blocked: needsAttentionCount,
    needsAttention: needsAttentionCount,
    ready: readyTasksCount,
    waitingDependencies: waitingDependencyCount,
    percent: taskCount ? Math.round((doneTasksCount / taskCount) * 100) : 0,
  };
}

export function missionHeaderStateForWorkbench({
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

export function finalPreviewStateForWorkbench({
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
  const { bundleEvidence, bundleRisks } = bundleEvidenceAndRisksForWorkbench({
    activeBundle,
    evidenceItems,
    isChineseUi,
    riskItems,
  });
  return {
    ...resultState,
    hasBundle: Boolean(activeBundle),
    canApprove: resultState.deliverable,
    evidenceItems: bundleEvidence,
    riskItems: bundleRisks,
    nextActionLabel: nextActionLabelForBundle(activeBundle, isChineseUi),
  };
}

export function userFacingResultForWorkbench({
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
  const { bundleEvidence, bundleRisks } = bundleEvidenceAndRisksForWorkbench({
    activeBundle,
    evidenceItems,
    isChineseUi,
    riskItems,
  });

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

export function finalAnswerStatusForBundle(bundle: AgentTeamMergeBundle | null) {
  const explicit = bundle?.final_answer_status?.trim();
  if (explicit) return explicit;
  if (!bundle) return null;
  return isBundleSimulated(bundle) ? "placeholder" : null;
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

function bundleEvidenceAndRisksForWorkbench({
  activeBundle,
  evidenceItems,
  isChineseUi,
  riskItems,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  evidenceItems: string[];
  isChineseUi: boolean;
  riskItems: string[];
}) {
  return {
    bundleEvidence: uniqueNonEmptyStrings([
      ...(activeBundle?.key_findings ?? []),
      ...(activeBundle?.test_evidence ?? []),
      ...(activeBundle?.changed_files ?? []),
      ...evidenceItems,
    ]),
    bundleRisks: uniqueNonEmptyStrings([
      ...(activeBundle?.risk_items ?? []),
      ...(activeBundle?.open_questions ?? []).map((question) =>
        isChineseUi ? `待确认：${question}` : `Open question: ${question}`,
      ),
      ...riskItems,
    ]),
  };
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
