import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { FieldList, StatusPill } from "./agent-team-workbench-shared";
import {
	artifactsForTask,
	outputsForTask,
} from "./agent-team-workbench-task-output-utils";
import type { useAgentTeamWorkbenchViewModel } from "./agent-team-workbench-view-model";
import {
	compactTaskGoal,
	runStatusText,
	statusLabel,
	taskTitle,
	uniqueNonEmptyStrings,
} from "./agent-team-workbench-utils";
import type {
	AgentTeamArtifact,
	AgentTeamSessionView,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";
import { useRetryAgentTeamTask } from "./use-agent-team";

type AgentTeamCockpitViewModel = ReturnType<
	typeof useAgentTeamWorkbenchViewModel
> & {
	primaryAction: ReturnType<
		typeof useAgentTeamWorkbenchViewModel
	>["primaryAction"] & {
		busy?: boolean;
		label: string;
	};
};

export interface AgentTeamCockpitProps {
	actions: {
		confirmResultPending: boolean;
		onConfirmResult: () => void;
		onGeneratePlan: () => void;
		onGenerateResult: () => void;
		onPrimaryAction: () => void;
		onRunReadyTasks: (taskIds?: string[]) => void;
		onSelectTask: (taskId: string) => void;
	};
	inspector: {
		isOpen: boolean;
		onToggle: () => void;
	};
	session: AgentTeamSessionView;
	viewModel: AgentTeamCockpitViewModel;
}

export function AgentTeamCockpit({
	actions,
	inspector,
	session,
	viewModel,
}: AgentTeamCockpitProps) {
	const { isChineseUi } = useShellUi();
	const selectedTaskState = viewModel.selectedTask
		? (viewModel.taskDisplayState[viewModel.selectedTask.task_id] ?? null)
		: null;
	const blockedTaskState = viewModel.taskDisplayStates.find(
		(state) => state.kind === "failed" || state.kind === "needs_attention",
	);
	const blockedTask = blockedTaskState
		? (viewModel.tasks.find(
				(task) => task.task_id === blockedTaskState.taskId,
			) ?? null)
		: null;

	return (
		<div className="fa-agent-team-cockpit-shell fa-agent-team-simple-shell">
			<MissionHeader
				actions={actions}
				blockedTask={blockedTask}
				blockedTaskState={blockedTaskState ?? null}
				session={session}
				viewModel={viewModel}
			/>
			{blockedTask ? (
				<BlockedTaskGuide
					actions={actions}
					task={blockedTask}
					taskState={blockedTaskState ?? null}
				/>
			) : (
				<MissionSteps viewModel={viewModel} />
			)}
			<main
				className="fa-agent-team-simple-main fa-agent-team-cockpit-grid"
				aria-label="Agent Team"
			>
				<div className="fa-agent-team-simple-left">
					<ExecutionGraph actions={actions} viewModel={viewModel} />
					<TaskList
						actions={actions}
						blockedTaskId={blockedTask?.task_id ?? null}
						viewModel={viewModel}
					/>
				</div>
				<div className="fa-agent-team-simple-right">
					<TaskDetail
						actions={actions}
						selectedTaskState={selectedTaskState}
						session={session}
						viewModel={viewModel}
					/>
					<OutputsPanel
						actions={actions}
						session={session}
						viewModel={viewModel}
					/>
					<FinalResultCard actions={actions} viewModel={viewModel} />
					<button
						aria-controls="agent-team-cockpit-inspector"
						aria-expanded={inspector.isOpen}
						className="fa-agent-team-simple-link-button"
						onClick={inspector.onToggle}
						type="button"
					>
						{isChineseUi ? "查看高级信息" : "Advanced details"}
					</button>
				</div>
			</main>
		</div>
	);
}

function MissionHeader({
	actions,
	blockedTask,
	blockedTaskState,
	session,
	viewModel,
}: {
	actions: AgentTeamCockpitProps["actions"];
	blockedTask: AgentTeamTask | null;
	blockedTaskState:
		| AgentTeamCockpitViewModel["taskDisplayStates"][number]
		| null;
	session: AgentTeamSessionView;
	viewModel: AgentTeamCockpitViewModel;
}) {
	const { isChineseUi } = useShellUi();
	const header = viewModel.missionHeaderState;
	const primaryDisabled =
		Boolean(viewModel.primaryAction.disabledReason) ||
		Boolean(viewModel.primaryAction.busy);
	const primaryClick = blockedTask
		? () => actions.onSelectTask(blockedTask.task_id)
		: actions.onPrimaryAction;
	const total = viewModel.missionProgress.total;
	const done = viewModel.missionProgress.done;
	const primaryHelp = blockedTask
		? blockedReasonInfo(blockedTask, blockedTaskState, isChineseUi).nextStep
		: (viewModel.primaryAction.disabledReason ?? viewModel.primaryAction.help);

	return (
		<section
			className={`fa-agent-team-simple-hero fa-agent-team-cockpit-mission-header is-${blockedTask ? "warning" : header.tone}`.trim()}
		>
			<div className="fa-agent-team-simple-hero-main">
				<span className="fa-agent-team-simple-kicker">Agent Team</span>
				<h1 {...tooltipProps(header.goal || session.session.goal)}>
					{header.title}
				</h1>
				<p
					{...tooltipProps(
						blockedTaskState?.help ??
							header.stageHelp ??
							viewModel.missionStage.help,
					)}
				>
					{blockedTask
						? isChineseUi
							? `任务卡住了：${taskTitle(blockedTask)}`
							: `Blocked task: ${taskTitle(blockedTask)}`
						: header.stageLabel}
				</p>
				<div className="fa-agent-team-simple-meta fa-agent-team-cockpit-mission-meta">
					<StatusPill status={blockedTask ? "blocked" : header.status} />
					<span>
						{total
							? isChineseUi
								? `${done}/${total} 个任务完成`
								: `${done}/${total} tasks done`
							: isChineseUi
								? "还没有任务"
								: "No tasks yet"}
					</span>
				</div>
				<div className="fa-agent-team-simple-progress" aria-hidden="true">
					<span style={{ width: `${header.progressPercent}%` }} />
				</div>
			</div>
			<div className="fa-agent-team-simple-hero-action">
				<span>
					{blockedTask
						? isChineseUi
							? "先处理这里"
							: "Handle this first"
						: isChineseUi
							? "现在就点这里"
							: "Click here next"}
				</span>
				<button
					aria-busy={viewModel.primaryAction.busy}
					className="fa-agent-team-cockpit-button is-primary"
					disabled={primaryDisabled}
					onClick={primaryClick}
					type="button"
					{...tooltipProps(primaryHelp)}
				>
					{blockedTask
						? isChineseUi
							? "先看卡住任务"
							: "Review blocked task"
						: viewModel.primaryAction.label}
				</button>
				<small>{primaryHelp}</small>
			</div>
		</section>
	);
}

function BlockedTaskGuide({
	actions,
	task,
	taskState,
}: {
	actions: AgentTeamCockpitProps["actions"];
	task: AgentTeamTask;
	taskState: AgentTeamCockpitViewModel["taskDisplayStates"][number] | null;
}) {
	const { isChineseUi } = useShellUi();
	const reasonInfo = blockedReasonInfo(task, taskState, isChineseUi);

	return (
		<section className="fa-agent-team-blocked-guide">
			<div>
				<span>{isChineseUi ? "下一步" : "Next"}</span>
				<strong>{reasonInfo.title}</strong>
				<p>{taskTitle(task)}</p>
				<small>{reasonInfo.reason}</small>
			</div>
			<button
				className="fa-agent-team-cockpit-button is-primary"
				onClick={() => actions.onSelectTask(task.task_id)}
				type="button"
			>
				{reasonInfo.actionLabel}
			</button>
		</section>
	);
}

function MissionSteps({ viewModel }: { viewModel: AgentTeamCockpitViewModel }) {
	const { isChineseUi } = useShellUi();
	const total = viewModel.missionProgress.total;
	const done = viewModel.missionProgress.done;
	const active =
		viewModel.missionProgress.running + viewModel.missionProgress.queued;
	const hasResult = viewModel.finalPreviewState.hasBundle;
	const steps = [
		{
			label: isChineseUi ? "DAG" : "DAG",
			value: total
				? isChineseUi
					? `${total} 个任务`
					: `${total} tasks`
				: isChineseUi
					? "未生成"
					: "Not planned",
			state: total ? "done" : "active",
		},
		{
			label: isChineseUi ? "运行" : "Run",
			value: active
				? isChineseUi
					? "进行中"
					: "Running"
				: `${done}/${total || 0}`,
			state: active
				? "active"
				: done && done < total
					? "ready"
					: total && done >= total
						? "done"
						: "idle",
		},
		{
			label: isChineseUi ? "交付" : "Deliver",
			value: hasResult
				? isChineseUi
					? "可查看"
					: "Ready"
				: isChineseUi
					? "等待"
					: "Pending",
			state: hasResult ? "done" : total && done >= total ? "ready" : "idle",
		},
	];

	return (
		<section
			className="fa-agent-team-simple-steps"
			aria-label={isChineseUi ? "Mission 状态" : "Mission status"}
		>
			{steps.map((step) => (
				<article
					className={`fa-agent-team-simple-step is-${step.state}`}
					key={step.label}
				>
					<span>{step.label}</span>
					<div>
						<strong>{step.value}</strong>
						<small>
							{step.state === "active"
								? isChineseUi
									? "当前"
									: "Current"
								: step.label}
						</small>
					</div>
				</article>
			))}
		</section>
	);
}

function ExecutionGraph({
	actions,
	viewModel,
}: {
	actions: AgentTeamCockpitProps["actions"];
	viewModel: AgentTeamCockpitViewModel;
}) {
	const { isChineseUi } = useShellUi();
	const graph = buildTaskGraph(viewModel.tasks);

	return (
		<section className="fa-agent-team-simple-panel fa-agent-team-execution-graph-panel">
			<header className="fa-agent-team-simple-panel-header">
				<div>
					<span>{isChineseUi ? "任务 DAG" : "Task DAG"}</span>
					<strong>
						{isChineseUi ? "依赖与执行状态" : "Dependencies and status"}
					</strong>
				</div>
			</header>
			{viewModel.tasks.length ? (
				<div className="fa-agent-team-graph-canvas">
					<div
						className="fa-agent-team-graph-main"
						style={{ height: graph.height, width: graph.width }}
					>
						<svg
							className="fa-agent-team-graph-lines"
							height={graph.height}
							viewBox={`0 0 ${graph.width} ${graph.height}`}
							width={graph.width}
							aria-hidden="true"
						>
							{graph.edges.map((edge) => {
								const from = graph.nodeById.get(edge.from);
								const to = graph.nodeById.get(edge.to);
								if (!from || !to) return null;
								return (
									<path
										className="fa-agent-team-graph-edge"
										d={taskEdgePath(from, to)}
										key={`${edge.from}-${edge.to}`}
									/>
								);
							})}
						</svg>
						{graph.nodes.map((node) => {
							const taskState = viewModel.taskDisplayState[node.task.task_id];
							const isSelected =
								viewModel.selectedTask?.task_id === node.task.task_id;
							const hasOutput = taskHasOutput(node.task, viewModel.view);
							return (
								<button
									className={`fa-agent-team-graph-node is-${taskState?.tone ?? "neutral"} ${isSelected ? "is-selected" : ""} ${hasOutput ? "has-output" : ""}`.trim()}
									key={node.task.task_id}
									onClick={() => actions.onSelectTask(node.task.task_id)}
									style={{ left: node.x, top: node.y }}
									title={`${taskTitle(node.task)} · ${taskExecutionLabel(node.task, taskState, isChineseUi)}`}
									type="button"
								>
									<span>
										{taskNodeLabel(node.task, taskState, isChineseUi)}
									</span>
								</button>
							);
						})}
					</div>
				</div>
			) : (
				<p>
					{isChineseUi
						? "生成任务后，这里会显示执行路径。"
						: "The execution path appears after tasks are planned."}
				</p>
			)}
		</section>
	);
}

function TaskList({
	actions,
	blockedTaskId,
	viewModel,
}: {
	actions: AgentTeamCockpitProps["actions"];
	blockedTaskId: string | null;
	viewModel: AgentTeamCockpitViewModel;
}) {
	const { isChineseUi } = useShellUi();
	const tasks = viewModel.tasks;

	return (
		<section
			className="fa-agent-team-simple-panel fa-agent-team-simple-task-list"
			aria-label={isChineseUi ? "任务" : "Tasks"}
		>
			<header className="fa-agent-team-simple-panel-header">
				<div>
					<span>{isChineseUi ? "任务" : "Tasks"}</span>
					<strong>
						{blockedTaskId
							? isChineseUi
								? "先处理标红任务"
								: "Handle the red task first"
							: isChineseUi
								? "任务清单"
								: "Task list"}
					</strong>
				</div>
			</header>
			{tasks.length ? (
				<div className="fa-agent-team-simple-tasks">
					{tasks.map((task) => {
						const taskState = viewModel.taskDisplayState[task.task_id];
						const isSelected = viewModel.selectedTask?.task_id === task.task_id;
						const isRecommended = viewModel.recommendedTaskId === task.task_id;
						const isBlocked = blockedTaskId === task.task_id;
						return (
							<button
								aria-pressed={isSelected}
								className={`fa-agent-team-simple-task is-${taskState?.tone ?? "neutral"} ${isSelected ? "is-selected" : ""} ${isRecommended ? "is-recommended" : ""} ${isBlocked ? "is-blocked-action" : ""}`.trim()}
								key={task.task_id}
								onClick={() => actions.onSelectTask(task.task_id)}
								type="button"
							>
								<span className="fa-agent-team-simple-task-index">
									{taskDependencyBadge(task, isChineseUi)}
								</span>
								<div className="fa-agent-team-simple-task-copy">
									<div>
										<strong>{taskTitle(task)}</strong>
										<StatusPill status={taskState?.kind ?? task.status} />
									</div>
									<div className="fa-agent-team-task-status-line">
										<span>
											{taskExecutionLabel(task, taskState, isChineseUi)}
										</span>
										{taskHasOutput(task, viewModel.view) ? (
											<span className="is-output-ready">
												{isChineseUi ? "有成果" : "Output ready"}
											</span>
										) : null}
										{task.attempt || task.max_attempts ? (
											<span>
												{isChineseUi ? "尝试" : "Attempt"} {task.attempt ?? 0}/
												{task.max_attempts ?? "?"}
											</span>
										) : null}
										{task.heartbeat_at ? (
											<span>{isChineseUi ? "有心跳" : "Heartbeat"}</span>
										) : null}
									</div>
									<p>
										{isBlocked
											? isChineseUi
												? "点这里查看原因和处理方式。"
												: "Click here to see the reason and next step."
											: compactTaskGoal(task.goal)}
									</p>
								</div>
							</button>
						);
					})}
				</div>
			) : (
				<div className="fa-agent-team-simple-empty">
					<strong>{isChineseUi ? "还没有任务" : "No tasks yet"}</strong>
					<p>
						{isChineseUi
							? "点上方主按钮生成任务。"
							: "Use the main button above to create tasks."}
					</p>
				</div>
			)}
		</section>
	);
}

function TaskDetail({
	actions,
	selectedTaskState,
	session,
	viewModel,
}: {
	actions: AgentTeamCockpitProps["actions"];
	selectedTaskState:
		| AgentTeamCockpitViewModel["taskDisplayStates"][number]
		| null;
	session: AgentTeamSessionView;
	viewModel: AgentTeamCockpitViewModel;
}) {
	const { isChineseUi } = useShellUi();
	const task = viewModel.selectedTask;
	const taskOutputs = task ? outputsForTask(session.outputs ?? [], task) : [];
	const taskArtifacts = task
		? artifactsForTask(session.artifacts ?? [], task, taskOutputs)
		: [];
	const canRunSelectedTask = Boolean(
		task &&
			selectedTaskState?.kind === "ready" &&
			!viewModel.primaryAction.busy,
	);
	const isBlocked =
		selectedTaskState?.kind === "failed" ||
		selectedTaskState?.kind === "needs_attention";
	const retryTask = useRetryAgentTeamTask(task?.session_id ?? null);
	const canRetryTask = Boolean(task && isBlocked && !retryTask.isPending);
	const reasonInfo =
		task && isBlocked
			? blockedReasonInfo(task, selectedTaskState, isChineseUi)
			: null;

	return (
		<details
			className={`fa-agent-team-simple-panel fa-agent-team-simple-detail ${isBlocked ? "is-blocked-detail" : ""}`.trim()}
			open={Boolean(task)}
		>
			<summary>
				{isBlocked
					? isChineseUi
						? "处理卡住的任务"
						: "Fix blocked task"
					: isChineseUi
						? "当前任务详情"
						: "Selected task details"}
			</summary>
			{task ? (
				<div className="fa-agent-team-simple-detail-body">
					<div className="fa-agent-team-simple-panel-header">
						<div>
							<span>
								{selectedTaskState?.label ??
									statusLabel(task.status, isChineseUi)}
							</span>
							<strong>{taskTitle(task)}</strong>
						</div>
					</div>
					{reasonInfo ? (
						<section className="fa-agent-team-fix-box">
							<h3>{isChineseUi ? "为什么卡住" : "Why it is blocked"}</h3>
							<p>{reasonInfo.reason}</p>
							<h3>{isChineseUi ? "现在怎么办" : "What to do now"}</h3>
							<p>{reasonInfo.nextStep}</p>
							<button
								className="fa-agent-team-cockpit-button is-primary"
								disabled={!canRetryTask}
								onClick={() =>
									task && retryTask.mutate({ taskId: task.task_id })
								}
								type="button"
							>
								{retryTask.isPending
									? isChineseUi
										? "重试中..."
										: "Retrying..."
									: isChineseUi
										? "重试这个任务"
										: "Retry this task"}
							</button>
						</section>
					) : null}
					<section>
						<h3>{isChineseUi ? "说明" : "Brief"}</h3>
						<p>{compactTaskGoal(task.goal)}</p>
					</section>
					<section>
						<h3>{isChineseUi ? "验收标准" : "Acceptance"}</h3>
						<FieldList items={task.acceptance_criteria} />
					</section>
					<section>
						<h3>{isChineseUi ? "成果" : "Output"}</h3>
						<p>
							{taskOutputSummary(task, taskOutputs, taskArtifacts, isChineseUi)}
						</p>
						<FieldList
							items={uniqueNonEmptyStrings([
								...taskOutputs.map((output) => output.summary),
								...taskArtifacts.map(
									(artifact) =>
										artifact.summary ?? artifact.title ?? artifact.uri,
								),
								task.verification_summary,
							])}
						/>
					</section>
					<button
						className="fa-agent-team-cockpit-button is-secondary"
						disabled={!canRunSelectedTask}
						onClick={() => actions.onRunReadyTasks([task.task_id])}
						type="button"
					>
						{isChineseUi ? "只运行这个任务" : "Run this task"}
					</button>
				</div>
			) : (
				<p>
					{isChineseUi
						? "生成任务后，这里会显示任务详情。"
						: "Task details will appear after planning."}
				</p>
			)}
		</details>
	);
}

function OutputsPanel({
	actions,
	session,
	viewModel,
}: {
	actions: AgentTeamCockpitProps["actions"];
	session: AgentTeamSessionView;
	viewModel: AgentTeamCockpitViewModel;
}) {
	const { isChineseUi } = useShellUi();
	const outputItems = taskOutputItems(viewModel.tasks, session);

	return (
		<section className="fa-agent-team-simple-panel fa-agent-team-outputs-panel">
			<header className="fa-agent-team-simple-panel-header">
				<div>
					<span>{isChineseUi ? "成果" : "Outputs"}</span>
					<strong>{isChineseUi ? "Agent 产出" : "Agent outputs"}</strong>
				</div>
			</header>
			{outputItems.length ? (
				<div className="fa-agent-team-output-cards">
					{outputItems.map((item) => (
						<button
							className="fa-agent-team-output-card"
							key={item.task.task_id}
							onClick={() => actions.onSelectTask(item.task.task_id)}
							type="button"
						>
							<strong>{taskTitle(item.task)}</strong>
							<p>{item.summary}</p>
							<span>{isChineseUi ? "点开看详情" : "Open details"}</span>
						</button>
					))}
				</div>
			) : (
				<p>
					{isChineseUi
						? "任务完成后，成果会出现在这里。"
						: "Completed task outputs will appear here."}
				</p>
			)}
		</section>
	);
}

function FinalResultCard({
	actions,
	viewModel,
}: {
	actions: AgentTeamCockpitProps["actions"];
	viewModel: AgentTeamCockpitViewModel;
}) {
	const { isChineseUi } = useShellUi();
	const finalState = viewModel.finalPreviewState;
	const evidence = finalState.evidenceItems.slice(0, 3);
	const risks = finalState.riskItems.slice(0, 3);

	return (
		<details
			className={`fa-agent-team-simple-panel fa-agent-team-simple-result is-${finalState.kind}`.trim()}
			open={finalState.hasBundle}
		>
			<summary>{isChineseUi ? "最终结果" : "Final result"}</summary>
			<div className="fa-agent-team-simple-detail-body">
				<header className="fa-agent-team-simple-panel-header">
					<div>
						<span>{isChineseUi ? "结果" : "Result"}</span>
						<small className="fa-sr-only">
							Decision Dock · Plan Review · Final Preview
						</small>
						<strong>{finalState.label}</strong>
					</div>
				</header>
				<p>{finalState.summary}</p>
				{!finalState.hasBundle ? (
					<p>
						{isChineseUi
							? "还没有最终汇总。你可以先查看上面的 Agent 产出。"
							: "No final summary yet. You can review the Agent outputs above."}
					</p>
				) : null}
				{evidence.length ? (
					<div>
						<h3>{isChineseUi ? "依据" : "Evidence"}</h3>
						<FieldList items={evidence} />
					</div>
				) : null}
				{risks.length ? (
					<div className="fa-agent-team-simple-warning">
						<h3>{isChineseUi ? "风险" : "Risks"}</h3>
						<FieldList items={risks} />
					</div>
				) : null}
				<button
					className="fa-agent-team-cockpit-button is-secondary"
					disabled={!finalState.deliverable || actions.confirmResultPending}
					onClick={actions.onConfirmResult}
					type="button"
				>
					{actions.confirmResultPending
						? isChineseUi
							? "确认中..."
							: "Approving..."
						: isChineseUi
							? "确认完成"
							: "Approve final"}
				</button>
			</div>
		</details>
	);
}

type TaskGraphNode = {
	index: number;
	task: AgentTeamTask;
	x: number;
	y: number;
};

type TaskGraph = {
	edges: Array<{ from: string; to: string }>;
	height: number;
	nodeById: Map<string, TaskGraphNode>;
	nodes: TaskGraphNode[];
	width: number;
};

function buildTaskGraph(tasks: AgentTeamTask[]): TaskGraph {
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

function taskEdgePath(from: TaskGraphNode, to: TaskGraphNode) {
	const startX = from.x + 14;
	const startY = from.y + 14;
	const endX = to.x + 14;
	const endY = to.y + 14;
	const offsetX = Math.max(28, Math.abs(endX - startX) * 0.45);
	return `M ${startX} ${startY} C ${startX + offsetX} ${startY}, ${endX - offsetX} ${endY}, ${endX} ${endY}`;
}

function taskHasOutput(
	task: AgentTeamTask,
	session: AgentTeamSessionView | null,
) {
	if (task.verification_summary?.trim()) return true;
	const outputs = outputsForTask(session?.outputs ?? [], task);
	const artifacts = artifactsForTask(session?.artifacts ?? [], task, outputs);
	return Boolean(outputs.length || artifacts.length);
}

function taskOutputItems(
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

function taskNodeLabel(
	task: AgentTeamTask,
	taskState: AgentTeamCockpitViewModel["taskDisplayStates"][number] | undefined,
	isChineseUi: boolean,
) {
	if (taskHasOutput(task, null)) return isChineseUi ? "果" : "Out";
	if (taskState?.kind === "running" || taskState?.kind === "queued")
		return isChineseUi ? "跑" : "Run";
	if ((task.dependencies ?? []).length) return isChineseUi ? "依" : "Dep";
	return isChineseUi ? "入" : "In";
}

function taskDependencyBadge(task: AgentTeamTask, isChineseUi: boolean) {
	const dependencyCount = task.dependencies?.length ?? 0;
	if (!dependencyCount) return isChineseUi ? "入口" : "Entry";
	return isChineseUi ? `依赖 ${dependencyCount}` : `Dep ${dependencyCount}`;
}

function taskExecutionLabel(
	task: AgentTeamTask,
	taskState: AgentTeamCockpitViewModel["taskDisplayStates"][number] | undefined,
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

function blockedReasonInfo(
	task: AgentTeamTask,
	taskState: AgentTeamCockpitViewModel["taskDisplayStates"][number] | null,
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

function taskOutputSummary(
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
