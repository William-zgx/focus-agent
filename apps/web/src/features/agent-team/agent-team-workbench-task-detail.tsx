import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { EmptyList, FieldList, HelpText } from "./agent-team-workbench-shared";
import {
	artifactsForTask,
	formatUnknown,
	hasFakeExecution,
	isRawRunText,
	outputsForTask,
	taskOutputEvidence,
	uniqueStrings,
} from "./agent-team-workbench-task-output-utils";
import { TaskReturnedSections } from "./agent-team-workbench-task-returned-sections";
import {
	displayTaskTitle,
	shortText,
	taskAttentionItems,
	taskExecutionMetadataItems,
	taskOutputRisks,
	taskResultSummary,
	taskSubtitle,
	UserTaskStatusPill,
	userTaskState,
} from "./agent-team-workbench-task-view-helpers";
import { runStatusDetails, runStatusText } from "./agent-team-workbench-utils";
import type {
	AgentTeamArtifact,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";

function TaskGuidedSections({
	artifacts = [],
	outputs = [],
	task,
	tasks,
}: {
	artifacts?: AgentTeamArtifact[];
	outputs?: AgentTeamTaskOutput[];
	task: AgentTeamTask;
	tasks: AgentTeamTask[];
}) {
	const { isChineseUi } = useShellUi();
	void tasks;
	const attentionItems = uniqueStrings([
		task.last_error,
		...(task.risk_notes ?? []),
		...taskOutputRisks(outputs),
	]);
	const evidenceItems = uniqueStrings([
		...taskOutputEvidence(outputs),
		...outputs.map((output) => output.summary),
		...artifacts.map((artifact) => artifact.summary ?? artifact.title),
	]).filter((item) => !isRawRunText(item));
	const fallbackEvidence = outputs.length
		? [
				hasFakeExecution(outputs)
					? isChineseUi
						? "模拟任务已回传；真实执行后会显示可验证依据。"
						: "The simulated task returned; verifiable evidence will appear after a real run."
					: isChineseUi
						? "任务已回传，暂无单独依据。"
						: "The task returned output; no separate evidence was provided.",
			]
		: [];

	return (
		<div className="fa-agent-team-detail">
			<section>
				<h3>{isChineseUi ? "为什么拆" : "Why this split"}</h3>
				<p>
					{shortText(
						task.planning_rationale || task.goal,
						isChineseUi ? "暂无拆解说明。" : "No split rationale yet.",
					)}
				</p>
			</section>
			<section>
				<h3>{isChineseUi ? "验收标准" : "Acceptance criteria"}</h3>
				<FieldList items={task.acceptance_criteria} />
			</section>
			<section>
				<h3>{isChineseUi ? "结果摘要" : "Result summary"}</h3>
				<p>{taskResultSummary(task, isChineseUi, outputs, artifacts)}</p>
			</section>
			<section>
				<h3>{isChineseUi ? "关键依据" : "Key evidence"}</h3>
				<FieldList
					items={evidenceItems.length ? evidenceItems : fallbackEvidence}
				/>
			</section>
			<section>
				<h3>{isChineseUi ? "需要注意" : "Needs attention"}</h3>
				<FieldList
					items={
						attentionItems.length
							? attentionItems
							: taskAttentionItems(task, isChineseUi)
					}
				/>
			</section>
		</div>
	);
}

export function TaskDetail({
	artifacts,
	outputs,
	task,
	tasks,
}: {
	artifacts: AgentTeamArtifact[];
	outputs: AgentTeamTaskOutput[];
	task: AgentTeamTask | null;
	tasks?: AgentTeamTask[];
}) {
	const { isChineseUi } = useShellUi();
	if (!task) {
		return (
			<EmptyList>
				{isChineseUi
					? "选择一个任务，这里会显示拆解原因、验收标准、结果摘要和注意事项。"
					: "Select a task to see why it exists, acceptance criteria, result summary, and notes."}
			</EmptyList>
		);
	}
	const taskOutputs = outputsForTask(outputs, task);
	const returnedArtifacts = artifactsForTask(artifacts, task, taskOutputs);
	const branchThreadId = task.child_thread_id ?? task.branch_id ?? "";
	const taskList = tasks?.length ? tasks : [task];
	const state = userTaskState(task, taskList);

	return (
		<div className="fa-agent-team-detail">
			<div className="fa-agent-team-detail-heading">
				<div>
					<span>{taskSubtitle(task, isChineseUi)}</span>
					<h2
						{...tooltipProps(task.goal || displayTaskTitle(task, isChineseUi))}
					>
						{displayTaskTitle(task, isChineseUi)}
					</h2>
					<HelpText>
						{isChineseUi
							? "这里默认只保留理解任务进展所需的信息。"
							: "This view keeps the default task progress details focused."}
					</HelpText>
				</div>
				<UserTaskStatusPill isChineseUi={isChineseUi} state={state} />
			</div>
			<TaskGuidedSections
				artifacts={returnedArtifacts}
				outputs={taskOutputs}
				task={task}
				tasks={taskList}
			/>
			<details className="fa-agent-team-advanced-details">
				<summary>{isChineseUi ? "高级详情" : "Advanced details"}</summary>
				<div className="fa-agent-team-meta-grid">
					<div>
						<span>{isChineseUi ? "任务 ID" : "Task ID"}</span>
						<code {...tooltipProps(task.task_id)}>{task.task_id}</code>
					</div>
					<div>
						<span>{isChineseUi ? "分支线程" : "Branch thread"}</span>
						<code {...tooltipProps(branchThreadId || task.task_id)}>
							{branchThreadId || "—"}
						</code>
					</div>
					<div>
						<span>{isChineseUi ? "任务类型" : "Task type"}</span>
						<code>{task.task_type ?? "—"}</code>
					</div>
					<div>
						<span>{isChineseUi ? "运行状态" : "Run status"}</span>
						<code>{runStatusText(task)}</code>
					</div>
					<div>
						<span>{isChineseUi ? "尝试次数" : "Attempts"}</span>
						<code>
							{task.attempt ?? 0}/{task.max_attempts ?? 0}
						</code>
					</div>
					<div>
						<span>{isChineseUi ? "队列时间" : "Queued at"}</span>
						<code>{task.queued_at ?? "—"}</code>
					</div>
					<div>
						<span>{isChineseUi ? "心跳" : "Heartbeat"}</span>
						<code>{task.heartbeat_at ?? task.claimed_until ?? "—"}</code>
					</div>
					<div>
						<span>{isChineseUi ? "执行模式" : "Execution mode"}</span>
						<code>{task.execution_mode ?? "—"}</code>
					</div>
				</div>
				<section>
					<h3>{isChineseUi ? "目标" : "Goal"}</h3>
					<p>{task.goal || "—"}</p>
				</section>
				<section>
					<h3>{isChineseUi ? "范围" : "Scope"}</h3>
					<FieldList items={task.scope} />
				</section>
				<section>
					<h3>{isChineseUi ? "依赖" : "Dependencies"}</h3>
					<FieldList items={task.dependencies} />
				</section>
				<section>
					<h3>{isChineseUi ? "Artifacts" : "Artifacts"}</h3>
					{returnedArtifacts.length ? (
						<div className="fa-agent-team-artifact-list">
							{returnedArtifacts.map((artifact) => (
								<article
									className="fa-agent-team-artifact-card"
									key={artifact.artifact_id}
								>
									<span>{artifact.kind ?? "artifact"}</span>
									<strong>{artifact.title ?? artifact.artifact_id}</strong>
									{artifact.summary ? <p>{artifact.summary}</p> : null}
								</article>
							))}
						</div>
					) : (
						<FieldList
							items={
								task.artifact_ids?.length
									? task.artifact_ids
									: task.output_artifact_ids
							}
						/>
					)}
				</section>
				<section>
					<h3>{isChineseUi ? "Output IDs" : "Output IDs"}</h3>
					<FieldList items={taskOutputs.map((output) => output.output_id)} />
				</section>
				<section>
					<h3>{isChineseUi ? "原始 output payload" : "Raw output payload"}</h3>
					<FieldList
						items={taskOutputs.map((output) =>
							formatUnknown(output.metadata ?? output),
						)}
					/>
				</section>
				<section>
					<h3>
						{isChineseUi ? "原始 artifact payload" : "Raw artifact payload"}
					</h3>
					<FieldList
						items={returnedArtifacts.map((artifact) =>
							formatUnknown(artifact.payload ?? artifact),
						)}
					/>
				</section>
				<section>
					<h3>{isChineseUi ? "原始运行状态" : "Raw run status"}</h3>
					<FieldList
						items={[
							...runStatusDetails(task),
							...taskExecutionMetadataItems(task, isChineseUi),
						]}
					/>
				</section>
				<TaskReturnedSections
					artifacts={returnedArtifacts}
					outputs={taskOutputs}
				/>
				<section>
					<h3>{isChineseUi ? "变更文件" : "Changed files"}</h3>
					<FieldList items={task.changed_files} />
				</section>
			</details>
		</div>
	);
}
