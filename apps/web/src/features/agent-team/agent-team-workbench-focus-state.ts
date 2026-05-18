import type { AgentTeamTaskDisplayState } from "./agent-team-workbench-utils";
import type { AgentTeamTask } from "./types";

export function shouldAutoAdvanceFocus({
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
	if (!recommendedTaskState || selectedTaskState?.kind !== "completed")
		return false;
	return (
		focusPriorityForTaskState(recommendedTaskState) <
		focusPriorityForTaskState(selectedTaskState)
	);
}

export function recommendedTaskStateForSelection(
	taskDisplayStates: AgentTeamTaskDisplayState[],
	tasks: AgentTeamTask[],
) {
	return (
		taskDisplayStates.find(
			(state) => state.kind === "failed" || state.kind === "needs_attention",
		) ??
		taskDisplayStates.find(
			(state) => state.kind === "running" || state.kind === "queued",
		) ??
		taskDisplayStates.find((state) => state.kind === "ready") ??
		[...taskDisplayStates]
			.filter((state) => state.kind === "completed")
			.sort(
				(left, right) =>
					timestampForTaskId(right.taskId, tasks) -
					timestampForTaskId(left.taskId, tasks),
			)[0] ??
		taskDisplayStates[0]
	);
}

export function recommendedTaskReasonForSelection({
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
		return isChineseUi
			? "还没有任务，先生成协作方案。"
			: "No tasks yet; generate the collaboration plan first.";
	}
	const state = taskDisplayState[selectedTask.task_id];
	if (
		isManualFocus &&
		recommendedTaskId &&
		recommendedTaskId !== selectedTask.task_id &&
		state?.kind !== "completed"
	) {
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
	const dependencyCount =
		state?.incompleteDependencies.length ??
		selectedTask.dependencies?.length ??
		0;
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

function timestampForTaskId(taskId: string, tasks: AgentTeamTask[]) {
	const task = tasks.find((item) => item.task_id === taskId);
	const timestamp = Date.parse(
		task?.finished_at ?? task?.updated_at ?? task?.created_at ?? "",
	);
	return Number.isFinite(timestamp) ? timestamp : 0;
}
