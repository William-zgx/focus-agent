import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { EmptyList } from "./agent-team-workbench-shared";
import {
	artifactsForTask,
	outputsForTask,
	taskOutputEvidence,
	uniqueStrings,
} from "./agent-team-workbench-task-output-utils";
import {
	displayTaskSummary,
	displayTaskTitle,
	taskDependencyLabel,
	taskInlineExecutionSummary,
	taskOutputRisks,
	taskResultSummary,
	taskSubtitle,
	UserTaskStatusPill,
	userTaskState,
	userTaskStateLabel,
} from "./agent-team-workbench-task-view-helpers";
import type {
	AgentTeamArtifact,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";

export function TaskBoard({
	artifacts = [],
	outputs = [],
	rootThreadId,
	selectedTaskId,
	tasks,
	onSelectTask,
}: {
	artifacts?: AgentTeamArtifact[];
	outputs?: AgentTeamTaskOutput[];
	rootThreadId: string;
	selectedTaskId: string | null;
	tasks: AgentTeamTask[];
	onSelectTask: (taskId: string) => void;
}) {
	const { isChineseUi } = useShellUi();
	void rootThreadId;
	if (!tasks.length) {
		return (
			<EmptyList>
				{isChineseUi
					? "还没有协作方案。先生成 Mission 拆解。"
					: "No collaboration plan yet. Generate the mission breakdown first."}
			</EmptyList>
		);
	}

	return (
		<div className="fa-agent-team-task-list fa-agent-team-task-timeline">
			{tasks.map((task) => {
				const taskSummary = displayTaskSummary(task, isChineseUi);
				const title = displayTaskTitle(task, isChineseUi);
				const taskTooltip = [task.planning_rationale, taskSummary]
					.filter(Boolean)
					.join(" · ");
				const taskOutputs = outputsForTask(outputs, task);
				const taskArtifacts = artifactsForTask(artifacts, task, taskOutputs);
				const taskEvidence = taskOutputEvidence(taskOutputs);
				const taskRiskCount = uniqueStrings([
					...(task.risk_notes ?? []),
					...taskOutputRisks(taskOutputs),
				]).length;
				const isSelected = selectedTaskId === task.task_id;
				const state = userTaskState(task, tasks);
				const executionSummary = taskInlineExecutionSummary(task, isChineseUi);
				return (
					<article
						className={`fa-agent-team-task-card fa-agent-team-task-step ${isSelected ? "is-selected" : ""}`.trim()}
						key={task.task_id}
						{...tooltipProps(taskTooltip)}
					>
						<button
							aria-expanded={isSelected}
							aria-label={`${title} · ${taskSummary}`}
							className="fa-agent-team-task-select"
							onClick={() => onSelectTask(task.task_id)}
							type="button"
						>
							<div className="fa-agent-team-task-topline">
								<div
									className="fa-agent-team-task-dependency-marker"
									aria-hidden="true"
								>
									<span>{taskDependencyLabel(task, isChineseUi)}</span>
									<i />
								</div>
								<div>
									<strong>{title}</strong>
									<span>
										{taskSubtitle(task, isChineseUi)} ·{" "}
										{userTaskStateLabel(state, isChineseUi)}
									</span>
								</div>
								<UserTaskStatusPill isChineseUi={isChineseUi} state={state} />
							</div>
							<p>{taskSummary}</p>
							<div className="fa-agent-team-task-result-summary fa-agent-team-task-return-preview">
								<span>{isChineseUi ? "回传摘要" : "Returned summary"}</span>
								<p>
									{taskResultSummary(
										task,
										isChineseUi,
										taskOutputs,
										taskArtifacts,
									)}
								</p>
								<small>
									{isChineseUi
										? `依据 ${taskEvidence.length} 条 · 风险 ${taskRiskCount} 条`
										: `${taskEvidence.length} evidence · ${taskRiskCount} risk${taskRiskCount === 1 ? "" : "s"}`}
								</small>
								{executionSummary ? <small>{executionSummary}</small> : null}
							</div>
						</button>
					</article>
				);
			})}
		</div>
	);
}
