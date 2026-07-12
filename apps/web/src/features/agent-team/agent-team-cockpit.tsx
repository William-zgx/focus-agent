import { useShellUi } from "@/app/shell/shell-ui-context";

import {
	BlockedTaskGuide,
	MissionHeader,
	MissionSteps,
} from "./agent-team-cockpit-mission";
import {
	ExecutionGraph,
	FinalResultCard,
	OutputsPanel,
	TaskDetail,
	TaskList,
} from "./agent-team-cockpit-panels";
import type { AgentTeamCockpitProps } from "./agent-team-cockpit-types";

export type { AgentTeamCockpitProps } from "./agent-team-cockpit-types";

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
