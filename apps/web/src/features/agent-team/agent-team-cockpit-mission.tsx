import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { StatusPill } from "./agent-team-workbench-shared";
import { taskTitle } from "./agent-team-workbench-utils";
import { blockedReasonInfo } from "./agent-team-cockpit-helpers";
import type {
	AgentTeamCockpitActions,
	AgentTeamCockpitTaskDisplayState,
	AgentTeamCockpitViewModel,
} from "./agent-team-cockpit-types";
import type { AgentTeamSessionView, AgentTeamTask } from "./types";

export function MissionHeader({
	actions,
	blockedTask,
	blockedTaskState,
	session,
	viewModel,
}: {
	actions: AgentTeamCockpitActions;
	blockedTask: AgentTeamTask | null;
	blockedTaskState: AgentTeamCockpitTaskDisplayState | null;
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

export function BlockedTaskGuide({
	actions,
	task,
	taskState,
}: {
	actions: AgentTeamCockpitActions;
	task: AgentTeamTask;
	taskState: AgentTeamCockpitTaskDisplayState | null;
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

export function MissionSteps({
	viewModel,
}: {
	viewModel: AgentTeamCockpitViewModel;
}) {
	const { isChineseUi } = useShellUi();
	const total = viewModel.missionProgress.total;
	const done = viewModel.missionProgress.done;
	const active =
		viewModel.missionProgress.running + viewModel.missionProgress.queued;
	const hasResult = viewModel.finalPreviewState.hasBundle;
	const steps = [
		{
			label: "DAG",
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
