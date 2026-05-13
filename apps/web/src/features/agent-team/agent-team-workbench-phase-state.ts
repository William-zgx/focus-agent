import {
  isTaskQueued,
  isTaskRunning,
  type AgentTeamTaskDisplayState,
} from "./agent-team-workbench-utils";
import type { AgentTeamTask } from "./types";

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

export function buildPhaseGroups(
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

export function buildPhaseMapItems({
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
