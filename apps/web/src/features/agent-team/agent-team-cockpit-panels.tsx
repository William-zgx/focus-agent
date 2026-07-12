import { useShellUi } from "@/app/shell/shell-ui-context";

import { FieldList, StatusPill } from "./agent-team-workbench-shared";
import {
	artifactsForTask,
	outputsForTask,
} from "./agent-team-workbench-task-output-utils";
import {
	compactTaskGoal,
	statusLabel,
	taskTitle,
	uniqueNonEmptyStrings,
} from "./agent-team-workbench-utils";
import {
	blockedReasonInfo,
	buildTaskGraph,
	taskDependencyBadge,
	taskEdgePath,
	taskExecutionLabel,
	taskHasOutput,
	taskNodeLabel,
	taskOutputItems,
	taskOutputSummary,
} from "./agent-team-cockpit-helpers";
import type {
	AgentTeamCockpitActions,
	AgentTeamCockpitTaskDisplayState,
	AgentTeamCockpitViewModel,
} from "./agent-team-cockpit-types";
import type { AgentTeamSessionView } from "./types";
import { useRetryAgentTeamTask } from "./use-agent-team";

export function ExecutionGraph({
	actions,
	viewModel,
}: {
	actions: AgentTeamCockpitActions;
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

export function TaskList({
	actions,
	blockedTaskId,
	viewModel,
}: {
	actions: AgentTeamCockpitActions;
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

export function TaskDetail({
	actions,
	selectedTaskState,
	session,
	viewModel,
}: {
	actions: AgentTeamCockpitActions;
	selectedTaskState: AgentTeamCockpitTaskDisplayState | null;
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

export function OutputsPanel({
	actions,
	session,
	viewModel,
}: {
	actions: AgentTeamCockpitActions;
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

export function FinalResultCard({
	actions,
	viewModel,
}: {
	actions: AgentTeamCockpitActions;
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
