import type {
	AgentTeamArtifact,
	AgentTeamMergeBundle,
	AgentTeamSession,
	AgentTeamSessionView,
	AgentTeamTask,
} from "./types";

export const STATUS_TONES: Record<
	string,
	"success" | "warning" | "danger" | "neutral"
> = {
	completed: "success",
	done: "success",
	awaiting_review: "warning",
	blocked: "warning",
	needs_attention: "warning",
	waiting_dependency: "neutral",
	merging: "warning",
	merge: "success",
	request_changes: "warning",
	split_followup: "warning",
	discard: "danger",
	failed: "danger",
	cancelled: "danger",
	planning: "neutral",
	pending: "neutral",
	queued: "neutral",
	ready: "neutral",
	running: "neutral",
};

export type AgentTeamTaskDisplayStateKind =
	| "completed"
	| "queued"
	| "running"
	| "waiting_dependency"
	| "ready"
	| "needs_attention"
	| "failed"
	| "pending";

export interface AgentTeamTaskDisplayState {
	taskId: string;
	kind: AgentTeamTaskDisplayStateKind;
	label: string;
	help: string;
	tone: "success" | "warning" | "danger" | "neutral";
	incompleteDependencies: string[];
	lastError: string | null;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function asStringArray(value: unknown): string[] {
	return Array.isArray(value)
		? value.map((item) => String(item)).filter(Boolean)
		: [];
}

export function uniqueNonEmptyStrings(
	values: Array<string | null | undefined>,
): string[] {
	return Array.from(
		new Set(values.map((value) => value?.trim() ?? "").filter(Boolean)),
	);
}

export function errorMessage(error: unknown, fallback: string) {
	return error instanceof Error ? error.message : fallback;
}

export function isUnsupportedLocalRuntimeError(error: unknown) {
	return (
		error instanceof Error &&
		/^Unsupported local runtime (API route|endpoint)\.$/.test(error.message)
	);
}

export function localRuntimeAgentTeamUnavailableMessage(isChineseUi: boolean) {
	return isChineseUi
		? "当前 Android 本地运行时暂不支持 Agent Team。请连接后端或关闭 Agent Team 入口。"
		: "Agent Team is not available in the Android local runtime. Connect a backend or disable the Agent Team entry.";
}

export function titleFromGoal(goal: string) {
	const normalized = goal.trim().replace(/\s+/g, " ");
	return normalized.length > 34
		? `${normalized.slice(0, 34)}…`
		: normalized || "Agent Team Session";
}

export function compactTaskGoal(goal: string) {
	const summary = goal
		.split("\n\nSession goal:", 1)[0]
		.trim()
		.replace(/\s+/g, " ");
	return summary.length > 96 ? `${summary.slice(0, 95)}…` : summary;
}

export function taskTitle(task: AgentTeamTask) {
	return task.title?.trim() || titleFromGoal(task.goal || task.task_id);
}

export function taskSubtitle(task: AgentTeamTask, isChineseUi: boolean) {
	const taskType = task.task_type?.trim();
	const planSource = task.plan_source?.trim();
	if (taskType && planSource) return `${taskType} · ${planSource}`;
	if (taskType) return taskType;
	if (planSource) return planSource;
	return isChineseUi ? "动态任务" : "Dynamic task";
}

export function runStatusText(task: AgentTeamTask) {
	if (typeof task.run_status === "string" && task.run_status.trim())
		return task.run_status;
	if (isRecord(task.run_status)) {
		return String(
			task.run_status.status ??
				task.run_status.state ??
				task.execution_status ??
				task.status,
		);
	}
	return String(task.execution_status ?? task.status);
}

export function runStatusDetails(task: AgentTeamTask): string[] {
	if (!isRecord(task.run_status))
		return uniqueNonEmptyStrings([task.execution_status ?? null]);
	return uniqueNonEmptyStrings([
		typeof task.run_status.run_id === "string"
			? `run_id: ${task.run_status.run_id}`
			: null,
		typeof task.run_status.message === "string"
			? task.run_status.message
			: null,
		typeof task.run_status.error === "string" ? task.run_status.error : null,
		typeof task.run_status.started_at === "string"
			? `started_at: ${task.run_status.started_at}`
			: null,
		typeof task.run_status.finished_at === "string"
			? `finished_at: ${task.run_status.finished_at}`
			: null,
	]);
}

export function isTaskRunning(task: AgentTeamTask) {
	if (task.status === "running") return true;
	if (typeof task.run_status === "string") return task.run_status === "running";
	if (isRecord(task.run_status)) {
		return (
			task.run_status.status === "running" ||
			task.run_status.state === "running"
		);
	}
	return task.execution_status === "running";
}

export function isTaskQueued(task: AgentTeamTask) {
	if (task.status === "queued") return true;
	if (typeof task.run_status === "string") return task.run_status === "queued";
	if (isRecord(task.run_status)) {
		return (
			task.run_status.status === "queued" || task.run_status.state === "queued"
		);
	}
	return task.execution_status === "queued";
}

export function isTaskDone(task: AgentTeamTask) {
	return (
		task.status === "done" ||
		task.status === "completed" ||
		runStatusText(task) === "done"
	);
}

export function isTaskReady(task: AgentTeamTask, tasks: AgentTeamTask[]) {
	const legacyPrimedTask =
		task.status === "running" &&
		!task.run_status &&
		!task.execution_status &&
		!task.agent_run_id;
	if (task.status !== "pending" && task.status !== "ready" && !legacyPrimedTask)
		return false;
	const doneTaskIds = new Set(
		tasks.filter(isTaskDone).map((item) => item.task_id),
	);
	return (task.dependencies ?? []).every((dependency) =>
		doneTaskIds.has(dependency),
	);
}

export function deriveTaskDisplayState(
	task: AgentTeamTask,
	tasks: AgentTeamTask[],
	isChineseUi: boolean,
): AgentTeamTaskDisplayState {
	const incompleteDependencies = taskIncompleteDependencies(task, tasks);
	const lastError = task.last_error?.trim() || null;

	if (isTaskDone(task)) {
		return {
			taskId: task.task_id,
			kind: "completed",
			label: isChineseUi ? "已完成" : "Completed",
			help: isChineseUi
				? "任务已完成，产出可用于最终结果。"
				: "The task is complete and ready for final synthesis.",
			tone: "success",
			incompleteDependencies,
			lastError,
		};
	}

	if (isTaskRunning(task)) {
		return {
			taskId: task.task_id,
			kind: "running",
			label: isChineseUi ? "执行中" : "Running",
			help: isChineseUi
				? "Agent 正在执行此任务。"
				: "An agent is running this task.",
			tone: "neutral",
			incompleteDependencies,
			lastError,
		};
	}

	if (isTaskQueued(task)) {
		return {
			taskId: task.task_id,
			kind: "queued",
			label: isChineseUi ? "排队中" : "Queued",
			help: isChineseUi
				? "任务已进入执行队列，等待 worker 领取。"
				: "The task is queued and waiting for a worker claim.",
			tone: "neutral",
			incompleteDependencies,
			lastError,
		};
	}

	if (task.status === "failed") {
		return {
			taskId: task.task_id,
			kind: "failed",
			label: isChineseUi ? "执行失败" : "Failed",
			help:
				lastError ??
				(isChineseUi
					? "任务执行失败，请查看详情后处理。"
					: "The task failed. Review details before continuing."),
			tone: "danger",
			incompleteDependencies,
			lastError,
		};
	}

	if (incompleteDependencies.length && isTaskWaitingForDependencies(task)) {
		return {
			taskId: task.task_id,
			kind: "waiting_dependency",
			label: isChineseUi ? "等待前置任务" : "Waiting for dependencies",
			help: isChineseUi
				? `等待 ${incompleteDependencies.length} 个前置任务完成。`
				: `Waiting for ${incompleteDependencies.length} dependencies to finish.`,
			tone: "neutral",
			incompleteDependencies,
			lastError,
		};
	}

	if (isTaskReady(task, tasks)) {
		return {
			taskId: task.task_id,
			kind: "ready",
			label: isChineseUi ? "可运行" : "Ready",
			help: isChineseUi
				? "前置任务已完成，可以运行此任务。"
				: "Dependencies are complete; this task can run.",
			tone: "neutral",
			incompleteDependencies,
			lastError,
		};
	}

	if (task.status === "blocked" && lastError) {
		return {
			taskId: task.task_id,
			kind: "needs_attention",
			label: isChineseUi ? "需要处理" : "Needs attention",
			help: lastError,
			tone: "warning",
			incompleteDependencies,
			lastError,
		};
	}

	return {
		taskId: task.task_id,
		kind: "pending",
		label: isChineseUi ? "等待开始" : "Waiting to start",
		help: isChineseUi
			? "任务已创建，尚未开始执行。"
			: "The task exists and has not started yet.",
		tone: "neutral",
		incompleteDependencies,
		lastError,
	};
}

export function deriveTaskDisplayStates(
	tasks: AgentTeamTask[],
	isChineseUi: boolean,
): AgentTeamTaskDisplayState[] {
	return tasks.map((task) => deriveTaskDisplayState(task, tasks, isChineseUi));
}

function taskIncompleteDependencies(
	task: AgentTeamTask,
	tasks: AgentTeamTask[],
) {
	const doneTaskIds = new Set(
		tasks.filter(isTaskDone).map((item) => item.task_id),
	);
	return uniqueNonEmptyStrings(
		(task.dependencies ?? []).filter(
			(dependency) => !doneTaskIds.has(dependency),
		),
	);
}

function isTaskWaitingForDependencies(task: AgentTeamTask) {
	return (
		task.status === "pending" ||
		task.status === "ready" ||
		task.status === "running"
	);
}

export function statusLabel(status: string, isChineseUi: boolean) {
	const labels: Record<string, string> = isChineseUi
		? {
				awaiting_review: "待生成结果",
				blocked: "需要处理",
				cancelled: "已取消",
				completed: "已完成",
				done: "已完成",
				failed: "执行失败",
				merging: "汇总中",
				merge: "可交付",
				needs_attention: "需要处理",
				request_changes: "需修改",
				split_followup: "拆分跟进",
				discard: "放弃",
				pending: "等待开始",
				planning: "规划中",
				queued: "排队中",
				ready: "可运行",
				running: "执行中",
				waiting_dependency: "等待前置任务",
			}
		: {
				awaiting_review: "Ready for result",
				blocked: "Needs attention",
				cancelled: "Cancelled",
				completed: "Completed",
				done: "Completed",
				failed: "Failed",
				merging: "Synthesizing",
				merge: "Deliverable",
				needs_attention: "Needs attention",
				request_changes: "Needs changes",
				split_followup: "Split follow-up",
				discard: "Discard",
				pending: "Waiting to start",
				planning: "Planning",
				queued: "Queued",
				ready: "Ready",
				running: "Running",
				waiting_dependency: "Waiting for dependencies",
			};
	return labels[status] ?? status.replaceAll("_", " ");
}

export function asMergeBundle(value: unknown): AgentTeamMergeBundle | null {
	return isRecord(value) ? (value as unknown as AgentTeamMergeBundle) : null;
}

export function normalizeSessionView(
	data: AgentTeamSession | AgentTeamSessionView | undefined,
): AgentTeamSessionView | null {
	if (!data) return null;
	if ("session" in data) {
		const planning = data.planning ?? data.session.planning ?? null;
		return {
			session: sessionWithPlanningMetadata(data.session, planning),
			tasks: data.tasks ?? [],
			outputs: data.outputs ?? [],
			artifacts: data.artifacts ?? [],
			merge_bundle:
				data.merge_bundle ??
				data.merge_suggestion ??
				data.session.latest_merge_bundle ??
				null,
			planning,
			evidence: data.evidence ?? [],
			risks: data.risks ?? [],
			dag: data.dag ?? null,
			merge_suggestion: data.merge_suggestion ?? null,
			run: data.run ?? null,
			pending_tool_approvals: data.pending_tool_approvals ?? [],
		};
	}

	const dataRecord = data as AgentTeamSession & Record<string, unknown>;
	return {
		session: data,
		tasks: Array.isArray(dataRecord.tasks)
			? (dataRecord.tasks as AgentTeamTask[])
			: [],
		outputs: Array.isArray(dataRecord.outputs)
			? (dataRecord.outputs as AgentTeamSessionView["outputs"])
			: [],
		artifacts: Array.isArray(dataRecord.artifacts)
			? (dataRecord.artifacts as AgentTeamArtifact[])
			: [],
		merge_bundle:
			asMergeBundle(dataRecord.merge_bundle) ??
			data.latest_merge_bundle ??
			null,
		planning: isRecord(dataRecord.planning) ? dataRecord.planning : null,
		evidence: asStringArray(dataRecord.evidence),
		risks: asStringArray(dataRecord.risks),
		dag: isRecord(dataRecord.dag) ? dataRecord.dag : null,
		merge_suggestion: asMergeBundle(dataRecord.merge_suggestion),
		run: isRecord(dataRecord.run) ? dataRecord.run : null,
		pending_tool_approvals: Array.isArray(dataRecord.pending_tool_approvals)
			? (dataRecord.pending_tool_approvals as AgentTeamSessionView["pending_tool_approvals"])
			: [],
	};
}

function sessionWithPlanningMetadata(
	session: AgentTeamSession,
	planning: AgentTeamSessionView["planning"],
): AgentTeamSession {
	if (!planning) return session;
	return {
		...session,
		planning_source: session.planning_source ?? planning.source ?? null,
		planning_rationale:
			session.planning_rationale ?? planning.rationale ?? null,
		planner_model_id:
			session.planner_model_id ?? planning.planner_model_id ?? null,
		plan_generated_at:
			session.plan_generated_at ?? planning.generated_at ?? null,
		plan_hash: session.plan_hash ?? planning.plan_hash ?? null,
		planning_error: session.planning_error ?? planning.error ?? null,
	};
}

export function normalizeMergeBundle(
	data: AgentTeamMergeBundle | AgentTeamSessionView | undefined,
): AgentTeamMergeBundle | null {
	if (!data) return null;
	if ("session" in data)
		return data.merge_bundle ?? data.session.latest_merge_bundle ?? null;
	return data;
}

export function defaultTaskActionLabel({
	isChineseUi,
	isPending,
	taskCount,
}: {
	isChineseUi: boolean;
	isPending: boolean;
	taskCount: number;
}) {
	if (isPending) return isChineseUi ? "生成中..." : "Planning...";
	if (taskCount) return isChineseUi ? "重新拆解" : "Replan";
	return isChineseUi ? "生成方案" : "Generate plan";
}

export function runReadyTasksActionLabel({
	isChineseUi,
	isPending,
	readyCount,
	runningCount,
}: {
	isChineseUi: boolean;
	isPending: boolean;
	readyCount: number;
	runningCount: number;
}) {
	if (isPending) return isChineseUi ? "启动中..." : "Starting...";
	if (runningCount) return isChineseUi ? "Mission 运行中" : "Mission running";
	if (!readyCount) return isChineseUi ? "暂无就绪任务" : "No ready tasks";
	return isChineseUi
		? `运行 Mission (${readyCount})`
		: `Run Mission (${readyCount})`;
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
	if (!canGenerate) return isChineseUi ? "先生成方案" : "Generate plan first";
	if (hasBundle) return isChineseUi ? "重新生成结果" : "Regenerate result";
	return isChineseUi ? "生成最终结果" : "Generate final result";
}

export function planningSourceLabel(
	source: string | null | undefined,
	isChineseUi: boolean,
) {
	const normalized = source?.trim();
	if (!normalized) return isChineseUi ? "尚未生成" : "Not planned";
	const labels: Record<string, string> = isChineseUi
		? {
				model: "模型规划",
				llm: "模型规划",
				delegation_runtime: "模型规划",
				dynamic: "动态规划",
				fallback: "保守协作方案",
				fallback_heuristic: "保守协作方案",
				conservative: "保守协作方案",
				default: "保守协作方案",
				legacy_template: "旧版模板",
			}
		: {
				model: "Model plan",
				llm: "Model plan",
				delegation_runtime: "Model plan",
				dynamic: "Dynamic plan",
				fallback: "Conservative plan",
				fallback_heuristic: "Conservative plan",
				conservative: "Conservative plan",
				default: "Conservative plan",
				legacy_template: "Legacy template",
			};
	return labels[normalized] ?? normalized.replaceAll("_", " ");
}

export function isFallbackPlan(
	session: AgentTeamSession | null,
	tasks: AgentTeamTask[],
) {
	const sessionSource = session?.planning_source?.toLowerCase() ?? "";
	if (session?.planning_error) return true;
	if (
		["fallback", "fallback_heuristic", "conservative", "default"].includes(
			sessionSource,
		)
	) {
		return true;
	}
	return tasks.some((task) =>
		["fallback", "fallback_heuristic", "conservative", "default"].includes(
			task.plan_source?.toLowerCase() ?? "",
		),
	);
}
