import type {
  AgentTeamArtifact,
  AgentTeamMergeBundle,
  AgentTeamRole,
  AgentTeamSession,
  AgentTeamSessionView,
  AgentTeamTask,
} from "./types";

export const DEFAULT_TASK_ROLES: AgentTeamRole[] = [
  "planner",
  "backend_executor",
  "frontend_executor",
  "test_engineer",
  "reviewer",
  "verifier",
];

export const STATUS_TONES: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  completed: "success",
  done: "success",
  awaiting_review: "warning",
  blocked: "warning",
  merging: "warning",
  merge: "success",
  request_changes: "warning",
  split_followup: "warning",
  discard: "danger",
  failed: "danger",
  cancelled: "danger",
  planning: "neutral",
  pending: "neutral",
  running: "neutral",
};

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

export function uniqueNonEmptyStrings(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.map((value) => value?.trim() ?? "").filter(Boolean)));
}

export function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function titleFromGoal(goal: string) {
  const normalized = goal.trim().replace(/\s+/g, " ");
  return normalized.length > 34 ? `${normalized.slice(0, 34)}…` : normalized || "Agent Team Session";
}

export function compactTaskGoal(goal: string) {
  const summary = goal.split("\n\nSession goal:", 1)[0].trim().replace(/\s+/g, " ");
  return summary.length > 96 ? `${summary.slice(0, 95)}…` : summary;
}

export function roleLabel(role: string, isChineseUi: boolean) {
  if (!isChineseUi) return role.replaceAll("_", " ");
  const labels: Record<string, string> = {
    planner: "规划",
    architect: "架构",
    backend_executor: "后端执行",
    frontend_executor: "前端执行",
    test_engineer: "测试",
    reviewer: "审查",
    verifier: "验证",
    writer: "文档",
  };
  return labels[role] ?? role.replaceAll("_", " ");
}

export function roleHint(role: string, isChineseUi: boolean) {
  if (!isChineseUi) {
    const hints: Record<string, string> = {
      planner: "Breaks the goal into lanes",
      backend_executor: "Builds service / API work",
      frontend_executor: "Builds UI / interaction work",
      test_engineer: "Locks behavior with tests",
      reviewer: "Finds risks before merge",
      verifier: "Checks completion evidence",
      writer: "Documents the result",
    };
    return hints[role] ?? "Agent task lane";
  }

  const hints: Record<string, string> = {
    planner: "拆目标和边界",
    backend_executor: "实现服务 / API",
    frontend_executor: "实现页面 / 交互",
    test_engineer: "补测试和用例",
    reviewer: "审查风险",
    verifier: "验证完成证据",
    writer: "沉淀文档",
  };
  return hints[role] ?? "Agent 分工";
}

export function taskGoalLabel(task: AgentTeamTask, isChineseUi: boolean) {
  const labels: Record<string, string> = isChineseUi
    ? {
        planner: "拆解目标与边界",
        backend_executor: "实现服务与 API",
        frontend_executor: "实现页面与交互",
        test_engineer: "补齐测试证据",
        reviewer: "审查回归与风险",
        verifier: "验证完成状态",
        writer: "整理协作文档",
      }
    : {
        planner: "Plan scope and boundaries",
        backend_executor: "Build service and API",
        frontend_executor: "Build UI and interactions",
        test_engineer: "Add test evidence",
        reviewer: "Review regressions and risks",
        verifier: "Verify completion",
        writer: "Document the collaboration",
      };

  return labels[task.role] ?? titleFromGoal(task.goal || task.task_id);
}

export function statusLabel(status: string, isChineseUi: boolean) {
  if (!isChineseUi) return status.replaceAll("_", " ");
  const labels: Record<string, string> = {
    awaiting_review: "待审查",
    blocked: "阻塞",
    cancelled: "已取消",
    completed: "已完成",
    done: "已完成",
    failed: "失败",
    merging: "汇总中",
    merge: "可合并",
    request_changes: "需修改",
    split_followup: "拆分跟进",
    discard: "放弃",
    pending: "待开始",
    planning: "规划中",
    running: "执行中",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

export function asMergeBundle(value: unknown): AgentTeamMergeBundle | null {
  return isRecord(value) ? (value as unknown as AgentTeamMergeBundle) : null;
}

export function normalizeSessionView(data: AgentTeamSession | AgentTeamSessionView | undefined): AgentTeamSessionView | null {
  if (!data) return null;
  if ("session" in data) {
    return {
      session: data.session,
      tasks: data.tasks ?? [],
      artifacts: data.artifacts ?? [],
      merge_bundle: data.merge_bundle ?? data.session.latest_merge_bundle ?? null,
    };
  }

  const dataRecord = data as AgentTeamSession & Record<string, unknown>;
  return {
    session: data,
    tasks: Array.isArray(dataRecord.tasks) ? (dataRecord.tasks as AgentTeamTask[]) : [],
    artifacts: Array.isArray(dataRecord.artifacts) ? (dataRecord.artifacts as AgentTeamArtifact[]) : [],
    merge_bundle: asMergeBundle(dataRecord.merge_bundle) ?? data.latest_merge_bundle ?? null,
  };
}

export function normalizeMergeBundle(
  data: AgentTeamMergeBundle | AgentTeamSessionView | undefined,
): AgentTeamMergeBundle | null {
  if (!data) return null;
  if ("session" in data) return data.merge_bundle ?? data.session.latest_merge_bundle ?? null;
  return data;
}

export function defaultTaskActionLabel({
  isChineseUi,
  isPending,
  defaultTasksReady,
  taskCount,
}: {
  isChineseUi: boolean;
  isPending: boolean;
  defaultTasksReady: boolean;
  taskCount: number;
}) {
  if (isPending) return isChineseUi ? "调度中..." : "Dispatching...";
  if (defaultTasksReady) return isChineseUi ? "默认任务已就绪" : "Default tasks ready";
  if (taskCount) return isChineseUi ? "补齐默认任务" : "Fill default tasks";
  return isChineseUi ? "生成 6 个任务" : "Create 6 tasks";
}

export function mergeBundleActionLabel({
  isChineseUi,
  isGenerating,
  canGenerate,
  hasBundle,
}: {
  isChineseUi: boolean;
  isGenerating: boolean;
  canGenerate: boolean;
  hasBundle: boolean;
}) {
  if (isGenerating) return isChineseUi ? "生成中..." : "Generating...";
  if (!canGenerate) return isChineseUi ? "先生成任务" : "Create tasks first";
  if (hasBundle) return isChineseUi ? "重新生成协作汇总" : "Regenerate summary";
  return isChineseUi ? "生成协作汇总" : "Generate summary";
}
