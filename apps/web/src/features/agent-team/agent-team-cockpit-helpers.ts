import {
	artifactsForTask,
	outputsForTask,
} from "./agent-team-workbench-task-output-utils";
import type { useAgentTeamWorkbenchViewModel } from "./agent-team-workbench-view-model";
import { runStatusText } from "./agent-team-workbench-utils";
import type {
	AgentTeamArtifact,
	AgentTeamSessionView,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";

type AgentTeamTaskDisplayState = ReturnType<
	typeof useAgentTeamWorkbenchViewModel
>["taskDisplayStates"][number];

export type TaskGraphNode = {
	index: number;
	task: AgentTeamTask;
	x: number;
	y: number;
};

export type TaskGraph = {
	edges: Array<{ from: string; to: string }>;
	height: number;
	nodeById: Map<string, TaskGraphNode>;
	nodes: TaskGraphNode[];
	width: number;
};

export function buildTaskGraph(tasks: AgentTeamTask[]): TaskGraph {
	const taskById = new Map(tasks.map((task) => [task.task_id, task]));
	const depthById = new Map<string, number>();

	function depthFor(task: AgentTeamTask): number {
		const cached = depthById.get(task.task_id);
		if (cached !== undefined) return cached;
		const dependencies = (task.dependencies ?? [])
			.map((id) => taskById.get(id))
			.filter((item): item is AgentTeamTask => Boolean(item));
		const depth = dependencies.length
			? Math.max(...dependencies.map(depthFor)) + 1
			: 0;
		depthById.set(task.task_id, depth);
		return depth;
	}

	for (const task of tasks) depthFor(task);
	const lanes = new Map<number, AgentTeamTask[]>();
	for (const task of tasks) {
		const depth = depthById.get(task.task_id) ?? 0;
		lanes.set(depth, [...(lanes.get(depth) ?? []), task]);
	}

	const nodes: TaskGraphNode[] = [];
	const xStart = 40;
	const yStart = 44;
	const xGap = 116;
	const yGap = 72;
	for (const [depth, laneTasks] of [...lanes.entries()].sort(
		([left], [right]) => left - right,
	)) {
		laneTasks.forEach((task, laneIndex) => {
			nodes.push({
				index: tasks.findIndex((item) => item.task_id === task.task_id),
				task,
				x: xStart + depth * xGap,
				y: yStart + laneIndex * yGap,
			});
		});
	}

	const nodeById = new Map(nodes.map((node) => [node.task.task_id, node]));
	const edges = tasks.flatMap((task) =>
		(task.dependencies ?? [])
			.filter((dependency) => nodeById.has(dependency))
			.map((dependency) => ({ from: dependency, to: task.task_id })),
	);
	const maxX = Math.max(...nodes.map((node) => node.x), xStart);
	const maxY = Math.max(...nodes.map((node) => node.y), yStart);
	return {
		edges,
		height: Math.max(180, maxY + 64),
		nodeById,
		nodes,
		width: Math.max(260, maxX + 80),
	};
}

export function taskEdgePath(from: TaskGraphNode, to: TaskGraphNode) {
	const startX = from.x + 14;
	const startY = from.y + 14;
	const endX = to.x + 14;
	const endY = to.y + 14;
	const offsetX = Math.max(28, Math.abs(endX - startX) * 0.45);
	return `M ${startX} ${startY} C ${startX + offsetX} ${startY}, ${endX - offsetX} ${endY}, ${endX} ${endY}`;
}

export function taskHasOutput(
	task: AgentTeamTask,
	session: AgentTeamSessionView | null,
) {
	if (task.verification_summary?.trim()) return true;
	const outputs = outputsForTask(session?.outputs ?? [], task);
	const artifacts = artifactsForTask(session?.artifacts ?? [], task, outputs);
	return Boolean(outputs.length || artifacts.length);
}

export function taskOutputItems(
	tasks: AgentTeamTask[],
	session: AgentTeamSessionView,
) {
	return tasks
		.map((task) => {
			const outputs = outputsForTask(session.outputs ?? [], task);
			const artifacts = artifactsForTask(
				session.artifacts ?? [],
				task,
				outputs,
			);
			const summary = taskOutputSummary(task, outputs, artifacts, false);
			if (!taskHasOutput(task, session)) return null;
			return { task, summary };
		})
		.filter((item): item is { summary: string; task: AgentTeamTask } =>
			Boolean(item),
		);
}

export function taskNodeLabel(
	task: AgentTeamTask,
	taskState: AgentTeamTaskDisplayState | undefined,
	isChineseUi: boolean,
) {
	if (taskHasOutput(task, null)) return isChineseUi ? "果" : "Out";
	if (taskState?.kind === "running" || taskState?.kind === "queued")
		return isChineseUi ? "跑" : "Run";
	if ((task.dependencies ?? []).length) return isChineseUi ? "依" : "Dep";
	return isChineseUi ? "入" : "In";
}

export function taskDependencyBadge(task: AgentTeamTask, isChineseUi: boolean) {
	const dependencyCount = task.dependencies?.length ?? 0;
	if (!dependencyCount) return isChineseUi ? "入口" : "Entry";
	return isChineseUi ? `依赖 ${dependencyCount}` : `Dep ${dependencyCount}`;
}

export function taskExecutionLabel(
	task: AgentTeamTask,
	taskState: AgentTeamTaskDisplayState | undefined,
	isChineseUi: boolean,
) {
	const runStatus = runStatusText(task).trim();
	const state = taskState?.kind;
	if (state === "running") return isChineseUi ? "正在执行" : "Running";
	if (state === "queued") return isChineseUi ? "排队中" : "Queued";
	if (state === "ready") return isChineseUi ? "可执行" : "Ready";
	if (state === "completed") return isChineseUi ? "已完成" : "Completed";
	if (state === "failed") return isChineseUi ? "失败" : "Failed";
	if (state === "needs_attention")
		return isChineseUi ? "需要处理" : "Needs attention";
	if (state === "waiting_dependency")
		return isChineseUi ? "等待前置任务" : "Waiting for dependency";
	if (runStatus && runStatus !== task.status)
		return isChineseUi ? `执行状态：${runStatus}` : `Run: ${runStatus}`;
	return isChineseUi ? "等待开始" : "Waiting";
}

export function blockedReasonInfo(
	task: AgentTeamTask,
	taskState: AgentTeamTaskDisplayState | null,
	isChineseUi: boolean,
) {
	const rawReason =
		taskState?.lastError || task.last_error || taskState?.help || "";
	if (
		/delegated execution is disabled|automatic task execution is not enabled/i.test(
			rawReason,
		)
	) {
		return {
			actionLabel: isChineseUi ? "查看下一步" : "Show next step",
			reason: isChineseUi
				? "当前环境没有开启自动执行任务，所以 Agent Team 不能继续帮你跑这个任务。"
				: "Automatic task execution is not enabled in this environment, so Agent Team cannot run this task for you.",
			nextStep: isChineseUi
				? "自动执行现在已开启。请点击下面的“重试这个任务”；如果仍失败，再查看新的失败原因。"
				: "Automatic execution is now enabled. Click “Retry this task” below; if it still fails, review the new error.",
			requiresExecutionSetup: false,
			title: isChineseUi ? "自动执行没有开启" : "Automatic execution is off",
		};
	}

	return {
		actionLabel: isChineseUi ? "查看怎么处理" : "Show what to fix",
		reason:
			rawReason ||
			(isChineseUi
				? "这个任务需要你先查看详情。"
				: "This task needs your review first."),
		nextStep: isChineseUi
			? "先根据上面的原因处理问题；处理完后，再用上方主按钮继续推进。"
			: "Fix the issue above, then use the main button at the top to continue.",
		requiresExecutionSetup: false,
		title: isChineseUi
			? "先处理这个卡住的任务"
			: "Handle this blocked task first",
	};
}

export function taskOutputSummary(
	task: AgentTeamTask | null,
	outputs: AgentTeamTaskOutput[],
	artifacts: AgentTeamArtifact[],
	isChineseUi: boolean,
) {
	const latestOutput = outputs[0];
	const latestArtifact = artifacts[0];
	const summary =
		latestOutput?.summary ??
		latestArtifact?.summary ??
		task?.verification_summary ??
		task?.last_error;
	if (summary?.trim()) return summary.trim();
	if (!task) return isChineseUi ? "还没有任务产出。" : "No task output yet.";
	if (task.status === "done" || task.status === "completed") {
		return isChineseUi
			? "任务已完成，等待汇总。"
			: "Task completed and ready for summary.";
	}
	return isChineseUi ? "还没有产出。" : "No output yet.";
}
