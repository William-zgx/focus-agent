import { useShellUi } from "@/app/shell/shell-ui-context";

import { HelpText } from "./agent-team-workbench-shared";
import { TaskBoard } from "./agent-team-workbench-task-board";
import { TaskDetail } from "./agent-team-workbench-task-detail";
import {
	canCancelTask,
	canRetryTask,
	taskRunAffordance,
} from "./agent-team-workbench-task-view-helpers";
import {
	defaultTaskActionLabel,
	errorMessage,
	isTaskReady,
} from "./agent-team-workbench-utils";
import type {
	AgentTeamArtifact,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";
import {
	useCancelAgentTeamTask,
	useRetryAgentTeamTask,
	useRunAgentTeamTask,
} from "./use-agent-team";

export { TaskBoard } from "./agent-team-workbench-task-board";
export { TaskDetail } from "./agent-team-workbench-task-detail";

export function TaskLanesPanel({
	artifacts,
	dispatchError,
	dispatchPending,
	onSelectTask,
	outputs,
	rootThreadId,
	selectedTaskId,
	onGeneratePlan,
	taskCount,
	tasks,
}: {
	artifacts?: AgentTeamArtifact[];
	dispatchError: Error | null;
	dispatchPending: boolean;
	onGeneratePlan: () => void;
	onSelectTask: (taskId: string) => void;
	outputs?: AgentTeamTaskOutput[];
	rootThreadId: string;
	selectedTaskId: string | null;
	taskCount: number;
	tasks: AgentTeamTask[];
}) {
	const { isChineseUi } = useShellUi();
	const readyCount = tasks.filter((task) => isTaskReady(task, tasks)).length;

	return (
		<section className="fa-agent-team-panel">
			<div className="fa-agent-team-panel-header">
				<div>
					<span>{isChineseUi ? "任务 DAG" : "Task DAG"}</span>
					<strong>
						{isChineseUi ? "计划任务与依赖" : "Planned work and dependencies"}
					</strong>
					<HelpText>
						{isChineseUi
							? "这里展示自动拆出的任务、依赖状态、回传产出和需要处理的风险。"
							: "Review generated tasks, dependency readiness, returned outputs, and risks that need attention."}
					</HelpText>
				</div>
				<button
					className="fa-observability-preset"
					disabled={dispatchPending}
					onClick={onGeneratePlan}
					type="button"
				>
					{defaultTaskActionLabel({
						isChineseUi,
						isPending: dispatchPending,
						taskCount,
					})}
				</button>
			</div>
			<HelpText>
				{isChineseUi
					? `当前有 ${readyCount} 个任务可以继续推进。`
					: `${readyCount} tasks are ready to move forward.`}
			</HelpText>
			{dispatchError ? (
				<div className="fa-inline-notice is-danger">
					{errorMessage(
						dispatchError,
						isChineseUi
							? "生成协作方案失败。"
							: "Failed to generate the collaboration plan.",
					)}
				</div>
			) : null}
			<TaskBoard
				artifacts={artifacts}
				outputs={outputs}
				rootThreadId={rootThreadId}
				selectedTaskId={selectedTaskId}
				tasks={tasks}
				onSelectTask={onSelectTask}
			/>
		</section>
	);
}

export function TaskDetailPanel({
	artifacts,
	outputs,
	selectedTask,
	tasks = [],
}: {
	artifacts: AgentTeamArtifact[];
	outputs: AgentTeamTaskOutput[];
	selectedTask: AgentTeamTask | null;
	tasks?: AgentTeamTask[];
}) {
	const { isChineseUi } = useShellUi();
	const runTask = useRunAgentTeamTask(selectedTask?.session_id ?? null);
	const retryTask = useRetryAgentTeamTask(selectedTask?.session_id ?? null);
	const cancelTask = useCancelAgentTeamTask(selectedTask?.session_id ?? null);
	const taskList = tasks.length ? tasks : selectedTask ? [selectedTask] : [];
	const action = selectedTask
		? taskRunAffordance({
				isChineseUi,
				isPending: runTask.isPending,
				task: selectedTask,
				tasks: taskList,
			})
		: null;
	const canRetry = selectedTask ? canRetryTask(selectedTask) : false;
	const canCancel = selectedTask ? canCancelTask(selectedTask) : false;
	const taskActionPending =
		runTask.isPending || retryTask.isPending || cancelTask.isPending;

	return (
		<section className="fa-agent-team-panel">
			<div className="fa-agent-team-panel-header">
				<div>
					<span>{isChineseUi ? "任务详情" : "Task details"}</span>
					<strong>{isChineseUi ? "任务详情" : "Task details"}</strong>
					<HelpText>
						{isChineseUi
							? "点击左侧任务可查看拆解原因、验收标准、结果摘要和注意事项。"
							: "Select a task to review why it exists, acceptance criteria, result summary, and notes."}
					</HelpText>
				</div>
				{selectedTask ? (
					<div className="fa-agent-team-task-actions">
						<button
							className="fa-observability-preset"
							disabled={!action?.canRun || taskActionPending}
							onClick={() => runTask.mutate({ taskId: selectedTask.task_id })}
							title={action?.disabledReason ?? action?.nextStep ?? undefined}
							type="button"
						>
							{action?.stateLabel}
						</button>
						<button
							className="fa-observability-preset"
							disabled={!canRetry || taskActionPending}
							onClick={() => retryTask.mutate({ taskId: selectedTask.task_id })}
							type="button"
						>
							{retryTask.isPending
								? isChineseUi
									? "重试中..."
									: "Retrying..."
								: isChineseUi
									? "重试"
									: "Retry"}
						</button>
						<button
							className="fa-observability-preset is-danger"
							disabled={!canCancel || taskActionPending}
							onClick={() =>
								cancelTask.mutate({ taskId: selectedTask.task_id })
							}
							type="button"
						>
							{cancelTask.isPending
								? isChineseUi
									? "取消中..."
									: "Cancelling..."
								: isChineseUi
									? "取消"
									: "Cancel"}
						</button>
					</div>
				) : null}
			</div>
			{action?.disabledReason ? (
				<div className="fa-inline-notice">
					{action.stateLabel} · {action.disabledReason}
				</div>
			) : null}
			{runTask.error ? (
				<div className="fa-inline-notice is-danger">
					{errorMessage(
						runTask.error,
						isChineseUi ? "执行失败。" : "Failed to run task.",
					)}
				</div>
			) : null}
			{retryTask.error ? (
				<div className="fa-inline-notice is-danger">
					{errorMessage(
						retryTask.error,
						isChineseUi ? "重试失败。" : "Failed to retry task.",
					)}
				</div>
			) : null}
			{cancelTask.error ? (
				<div className="fa-inline-notice is-danger">
					{errorMessage(
						cancelTask.error,
						isChineseUi ? "取消失败。" : "Failed to cancel task.",
					)}
				</div>
			) : null}
			<TaskDetail
				artifacts={artifacts}
				outputs={outputs}
				task={selectedTask}
				tasks={taskList}
			/>
		</section>
	);
}
