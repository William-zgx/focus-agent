import { useMemo, useState } from "react";

import {
  DEFAULT_TASK_ROLES,
  normalizeMergeBundle,
  normalizeSessionView,
  titleFromGoal,
  uniqueNonEmptyStrings,
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
    ...outputArtifactIds,
    ...(view?.artifacts ?? []).map((artifact) => artifact.summary ?? artifact.title ?? artifact.artifact_id),
    ...tasks.map((task) => task.verification_summary),
    ...(activeBundle?.test_evidence ?? []),
  ]);
  const taskRoles = new Set(tasks.map((task) => task.role));
  const defaultTasksReady = DEFAULT_TASK_ROLES.every((role) => taskRoles.has(role));
  const session = view?.session ?? null;
  const displayTitle = session?.title && session.title !== session.goal ? session.title : titleFromGoal(session?.goal ?? "");
  const nextStep = nextStepForWorkbench({
    activeBundle,
    changedFiles,
    evidenceItems,
    isChineseUi,
    tasks,
  });

  return {
    activeBundle,
    changedFiles,
    defaultTasksReady,
    displayTitle,
    evidenceItems,
    pendingBundle,
    selectedTask,
    setSelectedTaskId,
    tasks,
    view,
    nextStep,
  };
}

function nextStepForWorkbench({
  activeBundle,
  changedFiles,
  evidenceItems,
  isChineseUi,
  tasks,
}: {
  activeBundle: AgentTeamMergeBundle | null;
  changedFiles: string[];
  evidenceItems: string[];
  isChineseUi: boolean;
  tasks: AgentTeamTask[];
}) {
  if (!tasks.length) {
    return {
      label: isChineseUi ? "先生成默认任务，系统会创建 6 条协作分支" : "Create default tasks to add six collaboration branches",
      help: isChineseUi
        ? "生成 6 个默认任务，让规划、执行、测试、审查、验证各自有独立分支。"
        : "Create 6 default tasks so planning, execution, testing, review, and verification each get their own branch.",
    };
  }

  if (activeBundle?.recommended_next_action === "request_changes") {
    return {
      label: isChineseUi ? "合并前先处理风险和修改项" : "Resolve risks and requested changes before merge",
      help: isChineseUi
        ? "协作汇总已经生成，但仍有风险或阻塞项；先处理这些问题再进入合并。"
        : "The merge bundle exists, but risks or blockers remain. Resolve them before merging.",
    };
  }

  if (activeBundle) {
    return {
      label: isChineseUi ? "查看协作汇总并决定下一步" : "Review the merge bundle and decide the next action",
      help: isChineseUi
        ? "检查汇总里的改动、证据、风险和开放问题，再决定合并、拆分跟进或放弃。"
        : "Review changes, evidence, risks, and open questions before choosing merge, follow-up, or discard.",
    };
  }

  if (evidenceItems.length || changedFiles.length) {
    return {
      label: isChineseUi ? "已有产出后，生成协作汇总准备合并" : "Generate a merge summary once outputs are ready",
      help: isChineseUi
        ? "把产出、风险和验证证据收束成可审查建议。"
        : "Collect outputs, risks, and evidence into a reviewable recommendation.",
    };
  }

  return {
    label: isChineseUi ? "下一步：打开分支线程执行任务" : "Next: open branch threads and execute tasks",
    help: isChineseUi
      ? "打开任务线程，让对应 Agent 在分支里工作；产出会回到这里汇总。"
      : "Open task threads and let each agent work in its branch; outputs will roll back up here.",
  };
}
