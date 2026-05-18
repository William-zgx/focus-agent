import {
	hasFakeExecution,
	isRawRunText,
	latestTaskOutput,
	stringFromUnknown,
	taskOutputRisks,
	uniqueStrings,
} from "./agent-team-workbench-task-output-utils";
import {
	compactTaskGoal,
	isRecord,
	isTaskDone,
	isTaskQueued,
	isTaskReady,
	isTaskRunning,
	taskSubtitle,
	taskTitle,
} from "./agent-team-workbench-utils";
import type {
	AgentTeamArtifact,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";

export function shortText(value: string | null | undefined, fallback = "—") {
	const normalized = value?.trim().replace(/\s+/g, " ");
	if (!normalized) return fallback;
	return normalized.length > 140 ? `${normalized.slice(0, 139)}…` : normalized;
}

export function taskDependencyLabel(task: AgentTeamTask, isChineseUi: boolean) {
	const dependencyCount = task.dependencies?.length ?? 0;
	if (!dependencyCount) return isChineseUi ? "入口任务" : "Entry task";
	return isChineseUi
		? `依赖 ${dependencyCount} 个任务`
		: `Depends on ${dependencyCount}`;
}

export function displayTaskTitle(task: AgentTeamTask, isChineseUi: boolean) {
	return (
		task.title?.trim() ||
		(task.goal ? taskTitle(task) : isChineseUi ? "未命名任务" : "Untitled task")
	);
}

export function displayTaskSummary(task: AgentTeamTask, isChineseUi: boolean) {
	return task.goal
		? compactTaskGoal(task.goal)
		: isChineseUi
			? "暂无任务摘要。"
			: "No task summary yet.";
}

export function taskResultSummary(
	task: AgentTeamTask,
	isChineseUi: boolean,
	outputs: AgentTeamTaskOutput[] = [],
	artifacts: AgentTeamArtifact[] = [],
) {
	const latestOutput = latestTaskOutput(outputs);
	const latestArtifact = artifacts[0];
	const result =
		latestOutput?.summary ||
		latestArtifact?.summary ||
		task.verification_summary ||
		task.last_error;
	if (result && !isRawRunText(result) && !hasFakeExecution(outputs))
		return shortText(result);
	if (result && (isRawRunText(result) || hasFakeExecution(outputs))) {
		return isChineseUi
			? "模拟回传：流程已完成，但没有生成真实任务结果。"
			: "Simulated return: the flow completed, but no real task result was generated.";
	}
	if (task.status === "done" || task.status === "completed")
		return isChineseUi
			? "任务已完成，等待汇总结果。"
			: "Task completed and ready for synthesis.";
	if (isTaskRunning(task)) return isChineseUi ? "执行中。" : "Task is running.";
	if (task.status === "failed")
		return isChineseUi
			? "执行失败，查看需要注意。"
			: "Task failed. Check notes.";
	return isChineseUi ? "尚未产生运行结果。" : "No run result yet.";
}

export function outputExecutionItems(
	output: AgentTeamTaskOutput,
	isChineseUi: boolean,
) {
	const metadata = isRecord(output.metadata) ? output.metadata : {};
	const execution = isRecord(metadata.execution) ? metadata.execution : {};
	const run = isRecord(metadata.run) ? metadata.run : {};
	return uniqueStrings([
		stringFromUnknown(execution.execution_mode)
			? `${isChineseUi ? "执行模式" : "Mode"}: ${stringFromUnknown(execution.execution_mode)}`
			: null,
		stringFromUnknown(execution.execution_status || run.status)
			? `${isChineseUi ? "状态" : "Status"}: ${stringFromUnknown(execution.execution_status || run.status)}`
			: null,
		stringFromUnknown(execution.model_id || run.model_id)
			? `${isChineseUi ? "模型" : "Model"}: ${stringFromUnknown(execution.model_id || run.model_id)}`
			: null,
		stringFromUnknown(execution.started_at || run.started_at)
			? `${isChineseUi ? "开始" : "Started"}: ${stringFromUnknown(execution.started_at || run.started_at)}`
			: null,
		stringFromUnknown(execution.finished_at || run.finished_at)
			? `${isChineseUi ? "结束" : "Finished"}: ${stringFromUnknown(execution.finished_at || run.finished_at)}`
			: null,
	]);
}

export function artifactPayloadItems(
	artifact: AgentTeamArtifact,
	isChineseUi: boolean,
) {
	const payload = isRecord(artifact.payload) ? artifact.payload : {};
	return uniqueStrings([
		stringFromUnknown(payload.goal)
			? `${isChineseUi ? "目标" : "Goal"}: ${stringFromUnknown(payload.goal)}`
			: null,
		Array.isArray(payload.acceptance_criteria)
			? `${isChineseUi ? "验收标准" : "Acceptance"}: ${payload.acceptance_criteria.map(String).join("; ")}`
			: null,
		Array.isArray(payload.allowed_tools) && payload.allowed_tools.length
			? `${isChineseUi ? "允许工具" : "Allowed tools"}: ${payload.allowed_tools.map(String).join(", ")}`
			: null,
		typeof payload.deterministic === "boolean"
			? `${isChineseUi ? "确定性运行" : "Deterministic"}: ${String(payload.deterministic)}`
			: null,
	]);
}

export function taskAttentionItems(task: AgentTeamTask, isChineseUi: boolean) {
	const items = [task.last_error ?? "", ...(task.risk_notes ?? [])].filter(
		Boolean,
	);
	return items.length
		? items
		: [isChineseUi ? "暂无特别风险。" : "No special risks noted yet."];
}

export type UserTaskState =
	| "waiting_dependency"
	| "needs_attention"
	| "failed"
	| "ready"
	| "queued"
	| "running"
	| "done"
	| "waiting_start";

export function userTaskState(
	task: AgentTeamTask,
	tasks: AgentTeamTask[],
): UserTaskState {
	if (isTaskRunning(task)) return "running";
	if (isTaskQueued(task)) return "queued";
	if (isTaskDone(task)) return "done";
	if (task.status === "failed") return "failed";
	if (
		task.status === "blocked" ||
		task.status === "cancelled" ||
		task.last_error
	)
		return "needs_attention";
	if (task.status === "ready" || isTaskReady(task, tasks)) return "ready";
	if (
		(task.dependencies ?? []).length &&
		unresolvedDependencies(task, tasks).length
	)
		return "waiting_dependency";
	return "waiting_start";
}

export function userTaskStateLabel(state: UserTaskState, isChineseUi: boolean) {
	if (!isChineseUi) {
		const labels: Record<UserTaskState, string> = {
			waiting_dependency: "Waiting on prior tasks",
			needs_attention: "Needs attention",
			failed: "Failed",
			ready: "Ready to run",
			queued: "Queued",
			running: "Running",
			done: "Completed",
			waiting_start: "Waiting to start",
		};
		return labels[state];
	}
	const labels: Record<UserTaskState, string> = {
		waiting_dependency: "等待前置任务",
		needs_attention: "需要处理",
		failed: "执行失败",
		ready: "可运行",
		queued: "排队中",
		running: "执行中",
		done: "已完成",
		waiting_start: "等待开始",
	};
	return labels[state];
}

function userTaskStateTone(state: UserTaskState) {
	if (state === "done") return "success";
	if (state === "failed") return "danger";
	if (state === "waiting_dependency" || state === "needs_attention")
		return "warning";
	return "neutral";
}

export function canCancelTask(task: AgentTeamTask) {
	return (
		!task.cancel_requested_at && (isTaskQueued(task) || isTaskRunning(task))
	);
}

export function canRetryTask(task: AgentTeamTask) {
	return (
		task.status === "failed" ||
		task.status === "blocked" ||
		task.status === "cancelled"
	);
}

export function taskExecutionMetadataItems(
	task: AgentTeamTask,
	isChineseUi: boolean,
) {
	return uniqueStrings([
		typeof task.attempt === "number" || typeof task.max_attempts === "number"
			? `${isChineseUi ? "尝试" : "Attempt"}: ${task.attempt ?? 0}/${task.max_attempts ?? "?"}`
			: null,
		task.execution_mode
			? `${isChineseUi ? "模式" : "Mode"}: ${task.execution_mode}`
			: null,
		task.claim_owner
			? `${isChineseUi ? "领取者" : "Claim owner"}: ${task.claim_owner}`
			: null,
		task.claimed_until
			? `${isChineseUi ? "领取到期" : "Claimed until"}: ${task.claimed_until}`
			: null,
		task.queued_at
			? `${isChineseUi ? "排队时间" : "Queued at"}: ${task.queued_at}`
			: null,
		task.heartbeat_at
			? `${isChineseUi ? "心跳" : "Heartbeat"}: ${task.heartbeat_at}`
			: null,
		task.cancel_requested_at
			? `${isChineseUi ? "取消请求" : "Cancel requested"}: ${task.cancel_requested_at}`
			: null,
		task.last_error
			? `${isChineseUi ? "错误" : "Last error"}: ${task.last_error}`
			: null,
	]);
}

export function taskInlineExecutionSummary(
	task: AgentTeamTask,
	isChineseUi: boolean,
) {
	return uniqueStrings([
		typeof task.attempt === "number" || typeof task.max_attempts === "number"
			? `${isChineseUi ? "尝试" : "attempt"} ${task.attempt ?? 0}/${task.max_attempts ?? "?"}`
			: null,
		task.heartbeat_at
			? `${isChineseUi ? "心跳" : "heartbeat"} ${task.heartbeat_at}`
			: null,
		task.last_error
			? `${isChineseUi ? "错误" : "error"} ${shortText(task.last_error, "")}`
			: null,
	]).join(" · ");
}

export function UserTaskStatusPill({
	state,
	isChineseUi,
}: {
	isChineseUi: boolean;
	state: UserTaskState;
}) {
	return (
		<span className={`fa-agent-team-pill is-${userTaskStateTone(state)}`}>
			{userTaskStateLabel(state, isChineseUi)}
		</span>
	);
}

function doneTaskIdSet(tasks: AgentTeamTask[]) {
	return new Set(tasks.filter(isTaskDone).map((task) => task.task_id));
}

export function unresolvedDependencies(
	task: AgentTeamTask,
	tasks: AgentTeamTask[],
) {
	const doneIds = doneTaskIdSet(tasks);
	return (task.dependencies ?? []).filter(
		(dependency) => !doneIds.has(dependency),
	);
}

function dependencyWaitReason(
	task: AgentTeamTask,
	tasks: AgentTeamTask[],
	isChineseUi: boolean,
) {
	const dependencies = unresolvedDependencies(task, tasks);
	if (!dependencies.length) return null;
	const titles = dependencies
		.map((dependency) => tasks.find((item) => item.task_id === dependency))
		.filter((item): item is AgentTeamTask => Boolean(item))
		.map((item) => displayTaskTitle(item, isChineseUi));
	if (titles.length) {
		return isChineseUi
			? `等待前置任务完成：${titles.join("、")}`
			: `Waiting for prior tasks: ${titles.join(", ")}`;
	}
	return isChineseUi
		? `等待 ${dependencies.length} 个前置任务完成。`
		: `Waiting for ${dependencies.length} prior task${dependencies.length === 1 ? "" : "s"}.`;
}

export function taskRunAffordance({
	isChineseUi,
	isPending = false,
	task,
	tasks,
}: {
	isChineseUi: boolean;
	isPending?: boolean;
	task: AgentTeamTask;
	tasks: AgentTeamTask[];
}) {
	const state = userTaskState(task, tasks);
	const waitingReason = dependencyWaitReason(task, tasks, isChineseUi);
	const statusReady = task.status === "ready" || isTaskReady(task, tasks);

	if (isPending) {
		return {
			canRun: false,
			stateLabel: isChineseUi ? "运行此任务：运行中" : "Run task: running",
			disabledReason: isChineseUi ? "任务正在启动。" : "The task is starting.",
			nextStep: isChineseUi ? "等待启动完成。" : "Wait for startup to finish.",
		};
	}

	if (state === "running") {
		return {
			canRun: false,
			stateLabel: isChineseUi ? "运行此任务：运行中" : "Run task: running",
			disabledReason: isChineseUi
				? "任务正在执行。"
				: "The task is currently running.",
			nextStep: isChineseUi
				? "等待结果和需要注意的事项回传。"
				: "Wait for results and notes to return.",
		};
	}

	if (state === "queued") {
		return {
			canRun: false,
			stateLabel: isChineseUi ? "运行此任务：排队中" : "Run task: queued",
			disabledReason: isChineseUi
				? "任务已进入后台队列。"
				: "The task is already queued.",
			nextStep: isChineseUi
				? "等待 worker 领取任务。"
				: "Wait for a worker to claim the task.",
		};
	}

	if (state === "done") {
		return {
			canRun: false,
			stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
			disabledReason: isChineseUi
				? "任务已完成。"
				: "The task is already complete.",
			nextStep: isChineseUi
				? "查看结果，或在所有任务完成后生成最终结果。"
				: "Review the result, or generate the final result after all tasks complete.",
		};
	}

	if (state === "failed") {
		return {
			canRun: false,
			stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
			disabledReason: shortText(
				task.last_error,
				isChineseUi
					? "先处理执行失败原因。"
					: "Resolve the failure before running again.",
			),
			nextStep: isChineseUi
				? "查看需要注意的事项，处理后重新拆解或继续运行。"
				: "Review notes, address the issue, then replan or continue running.",
		};
	}

	if (state === "needs_attention") {
		return {
			canRun: false,
			stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
			disabledReason: shortText(
				task.last_error,
				isChineseUi
					? "需要先处理此任务的问题。"
					: "Resolve this task's issue before running.",
			),
			nextStep: isChineseUi
				? "处理风险、缺口或人工判断后再继续。"
				: "Address risks, gaps, or required review before continuing.",
		};
	}

	if (statusReady) {
		return {
			canRun: true,
			stateLabel: isChineseUi ? "运行此任务：可用" : "Run task: available",
			disabledReason: null,
			nextStep: isChineseUi
				? "可以单独运行此任务。"
				: "This task can be run on its own.",
		};
	}

	if (waitingReason) {
		return {
			canRun: false,
			stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
			disabledReason: waitingReason,
			nextStep: isChineseUi
				? "先完成前置任务，再回来运行这一项。"
				: "Complete prior tasks first, then return to this one.",
		};
	}

	return {
		canRun: false,
		stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
		disabledReason: isChineseUi
			? "任务还在等待开始。"
			: "The task is waiting to start.",
		nextStep: isChineseUi
			? "先运行 Mission，或选择已经可运行的任务。"
			: "Run the mission first, or choose a task that is ready.",
	};
}

export { taskOutputRisks, taskSubtitle };
