import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import {
  compactTaskGoal,
  defaultTaskActionLabel,
  errorMessage,
  isRecord,
  isTaskDone,
  isTaskQueued,
  isTaskReady,
  isTaskRunning,
  runStatusDetails,
  runStatusText,
  taskSubtitle,
  taskTitle,
} from "./agent-team-workbench-utils";
import { EmptyList, FieldList, HelpText } from "./agent-team-workbench-shared";
import {
  artifactsForTask,
  formatUnknown,
  hasFakeExecution,
  isRawRunText,
  latestTaskOutput,
  outputsForTask,
  stringFromUnknown,
  taskOutputEvidence,
  taskOutputRisks,
  uniqueStrings,
} from "./agent-team-workbench-task-output-utils";
import { useCancelAgentTeamTask, useRetryAgentTeamTask, useRunAgentTeamTask } from "./use-agent-team";
import type { AgentTeamArtifact, AgentTeamTask, AgentTeamTaskOutput } from "./types";

function shortText(value: string | null | undefined, fallback = "—") {
  const normalized = value?.trim().replace(/\s+/g, " ");
  if (!normalized) return fallback;
  return normalized.length > 140 ? `${normalized.slice(0, 139)}…` : normalized;
}

function taskDependencyLabel(task: AgentTeamTask, isChineseUi: boolean) {
  const dependencyCount = task.dependencies?.length ?? 0;
  if (!dependencyCount) return isChineseUi ? "入口任务" : "Entry task";
  return isChineseUi ? `依赖 ${dependencyCount} 个任务` : `Depends on ${dependencyCount}`;
}

function displayTaskTitle(task: AgentTeamTask, isChineseUi: boolean) {
  return task.title?.trim() || (task.goal ? taskTitle(task) : isChineseUi ? "未命名任务" : "Untitled task");
}

function displayTaskSummary(task: AgentTeamTask, isChineseUi: boolean) {
  return task.goal ? compactTaskGoal(task.goal) : isChineseUi ? "暂无任务摘要。" : "No task summary yet.";
}

function taskResultSummary(
  task: AgentTeamTask,
  isChineseUi: boolean,
  outputs: AgentTeamTaskOutput[] = [],
  artifacts: AgentTeamArtifact[] = [],
) {
  const latestOutput = latestTaskOutput(outputs);
  const latestArtifact = artifacts[0];
  const result = latestOutput?.summary || latestArtifact?.summary || task.verification_summary || task.last_error;
  if (result && !isRawRunText(result) && !hasFakeExecution(outputs)) return shortText(result);
  if (result && (isRawRunText(result) || hasFakeExecution(outputs))) {
    return isChineseUi
      ? "模拟回传：流程已完成，但没有生成真实任务结果。"
      : "Simulated return: the flow completed, but no real task result was generated.";
  }
  if (task.status === "done" || task.status === "completed") return isChineseUi ? "任务已完成，等待汇总结果。" : "Task completed and ready for synthesis.";
  if (isTaskRunning(task)) return isChineseUi ? "执行中。" : "Task is running.";
  if (task.status === "failed") return isChineseUi ? "执行失败，查看需要注意。" : "Task failed. Check notes.";
  return isChineseUi ? "尚未产生运行结果。" : "No run result yet.";
}

function outputExecutionItems(output: AgentTeamTaskOutput, isChineseUi: boolean) {
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

function artifactPayloadItems(artifact: AgentTeamArtifact, isChineseUi: boolean) {
  const payload = isRecord(artifact.payload) ? artifact.payload : {};
  return uniqueStrings([
    stringFromUnknown(payload.goal) ? `${isChineseUi ? "目标" : "Goal"}: ${stringFromUnknown(payload.goal)}` : null,
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

function taskAttentionItems(task: AgentTeamTask, isChineseUi: boolean) {
  const items = [task.last_error ?? "", ...(task.risk_notes ?? [])].filter(Boolean);
  return items.length ? items : [isChineseUi ? "暂无特别风险。" : "No special risks noted yet."];
}

type UserTaskState =
  | "waiting_dependency"
  | "needs_attention"
  | "failed"
  | "ready"
  | "queued"
  | "running"
  | "done"
  | "waiting_start";

function userTaskState(task: AgentTeamTask, tasks: AgentTeamTask[]): UserTaskState {
  if (isTaskRunning(task)) return "running";
  if (isTaskQueued(task)) return "queued";
  if (isTaskDone(task)) return "done";
  if (task.status === "failed") return "failed";
  if (task.status === "blocked" || task.status === "cancelled" || task.last_error) return "needs_attention";
  if (task.status === "ready" || isTaskReady(task, tasks)) return "ready";
  if ((task.dependencies ?? []).length && unresolvedDependencies(task, tasks).length) return "waiting_dependency";
  return "waiting_start";
}

function userTaskStateLabel(state: UserTaskState, isChineseUi: boolean) {
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
  if (state === "waiting_dependency" || state === "needs_attention") return "warning";
  return "neutral";
}

function canCancelTask(task: AgentTeamTask) {
  return !task.cancel_requested_at && (isTaskQueued(task) || isTaskRunning(task));
}

function canRetryTask(task: AgentTeamTask) {
  return task.status === "failed" || task.status === "blocked" || task.status === "cancelled";
}

function taskExecutionMetadataItems(task: AgentTeamTask, isChineseUi: boolean) {
  return uniqueStrings([
    typeof task.attempt === "number" || typeof task.max_attempts === "number"
      ? `${isChineseUi ? "尝试" : "Attempt"}: ${task.attempt ?? 0}/${task.max_attempts ?? "?"}`
      : null,
    task.execution_mode ? `${isChineseUi ? "模式" : "Mode"}: ${task.execution_mode}` : null,
    task.claim_owner ? `${isChineseUi ? "领取者" : "Claim owner"}: ${task.claim_owner}` : null,
    task.claimed_until ? `${isChineseUi ? "领取到期" : "Claimed until"}: ${task.claimed_until}` : null,
    task.queued_at ? `${isChineseUi ? "排队时间" : "Queued at"}: ${task.queued_at}` : null,
    task.heartbeat_at ? `${isChineseUi ? "心跳" : "Heartbeat"}: ${task.heartbeat_at}` : null,
    task.cancel_requested_at ? `${isChineseUi ? "取消请求" : "Cancel requested"}: ${task.cancel_requested_at}` : null,
    task.last_error ? `${isChineseUi ? "错误" : "Last error"}: ${task.last_error}` : null,
  ]);
}

function taskInlineExecutionSummary(task: AgentTeamTask, isChineseUi: boolean) {
  return uniqueStrings([
    typeof task.attempt === "number" || typeof task.max_attempts === "number"
      ? `${isChineseUi ? "尝试" : "attempt"} ${task.attempt ?? 0}/${task.max_attempts ?? "?"}`
      : null,
    task.heartbeat_at ? `${isChineseUi ? "心跳" : "heartbeat"} ${task.heartbeat_at}` : null,
    task.last_error ? `${isChineseUi ? "错误" : "error"} ${shortText(task.last_error, "")}` : null,
  ]).join(" · ");
}

function UserTaskStatusPill({ state, isChineseUi }: { isChineseUi: boolean; state: UserTaskState }) {
  return (
    <span className={`fa-agent-team-pill is-${userTaskStateTone(state)}`}>
      {userTaskStateLabel(state, isChineseUi)}
    </span>
  );
}

function doneTaskIdSet(tasks: AgentTeamTask[]) {
  return new Set(tasks.filter(isTaskDone).map((task) => task.task_id));
}

function unresolvedDependencies(task: AgentTeamTask, tasks: AgentTeamTask[]) {
  const doneIds = doneTaskIdSet(tasks);
  return (task.dependencies ?? []).filter((dependency) => !doneIds.has(dependency));
}

function dependencyWaitReason(task: AgentTeamTask, tasks: AgentTeamTask[], isChineseUi: boolean) {
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

function taskRunAffordance({
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
      disabledReason: isChineseUi ? "任务正在执行。" : "The task is currently running.",
      nextStep: isChineseUi ? "等待结果和需要注意的事项回传。" : "Wait for results and notes to return.",
    };
  }

  if (state === "queued") {
    return {
      canRun: false,
      stateLabel: isChineseUi ? "运行此任务：排队中" : "Run task: queued",
      disabledReason: isChineseUi ? "任务已进入后台队列。" : "The task is already queued.",
      nextStep: isChineseUi ? "等待 worker 领取任务。" : "Wait for a worker to claim the task.",
    };
  }

  if (state === "done") {
    return {
      canRun: false,
      stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
      disabledReason: isChineseUi ? "任务已完成。" : "The task is already complete.",
      nextStep: isChineseUi ? "查看结果，或在所有任务完成后生成最终结果。" : "Review the result, or generate the final result after all tasks complete.",
    };
  }

  if (state === "failed") {
    return {
      canRun: false,
      stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
      disabledReason: shortText(task.last_error, isChineseUi ? "先处理执行失败原因。" : "Resolve the failure before running again."),
      nextStep: isChineseUi ? "查看需要注意的事项，处理后重新拆解或继续运行。" : "Review notes, address the issue, then replan or continue running.",
    };
  }

  if (state === "needs_attention") {
    return {
      canRun: false,
      stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
      disabledReason: shortText(task.last_error, isChineseUi ? "需要先处理此任务的问题。" : "Resolve this task's issue before running."),
      nextStep: isChineseUi ? "处理风险、缺口或人工判断后再继续。" : "Address risks, gaps, or required review before continuing.",
    };
  }

  if (statusReady) {
    return {
      canRun: true,
      stateLabel: isChineseUi ? "运行此任务：可用" : "Run task: available",
      disabledReason: null,
      nextStep: isChineseUi ? "可以单独运行此任务。" : "This task can be run on its own.",
    };
  }

  if (waitingReason) {
    return {
      canRun: false,
      stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
      disabledReason: waitingReason,
      nextStep: isChineseUi ? "先完成前置任务，再回来运行这一项。" : "Complete prior tasks first, then return to this one.",
    };
  }

  return {
    canRun: false,
    stateLabel: isChineseUi ? "运行此任务：不可用" : "Run task: unavailable",
    disabledReason: isChineseUi ? "任务还在等待开始。" : "The task is waiting to start.",
    nextStep: isChineseUi ? "先运行 Mission，或选择已经可运行的任务。" : "Run the mission first, or choose a task that is ready.",
  };
}

function TaskReturnedSections({
  artifacts,
  outputs,
}: {
  artifacts: AgentTeamArtifact[];
  outputs: AgentTeamTaskOutput[];
}) {
  const { isChineseUi } = useShellUi();
  if (!outputs.length && !artifacts.length) {
    return (
      <section>
        <h3>{isChineseUi ? "任务回传" : "Task return"}</h3>
        <EmptyList>{isChineseUi ? "还没有收到这个任务的回传内容。" : "No returned content for this task yet."}</EmptyList>
      </section>
    );
  }

  return (
    <>
      <section>
        <h3>{isChineseUi ? "任务回传" : "Task return"}</h3>
        {outputs.length ? (
          <div className="fa-agent-team-output-list">
            {outputs.map((output) => (
              <div className="fa-agent-team-output-row" key={output.output_id}>
                <div className="fa-agent-team-output-row-heading">
                  <span>{output.kind ?? (isChineseUi ? "回传" : "output")}</span>
                  <strong>{shortText(output.summary, isChineseUi ? "已回传，但没有摘要。" : "Returned without a summary.")}</strong>
                </div>
                <div className="fa-agent-team-output-columns">
                  <div>
                    <span>{isChineseUi ? "依据" : "Evidence"}</span>
                    <FieldList items={output.test_evidence} />
                  </div>
                  <div>
                    <span>{isChineseUi ? "运行信息" : "Run info"}</span>
                    <FieldList items={outputExecutionItems(output, isChineseUi)} />
                  </div>
                </div>
                {output.risk_notes?.length ? (
                  <div>
                    <span>{isChineseUi ? "风险" : "Risks"}</span>
                    <FieldList items={output.risk_notes} />
                  </div>
                ) : null}
                {output.changed_files?.length ? (
                  <div>
                    <span>{isChineseUi ? "改动文件" : "Changed files"}</span>
                    <FieldList items={output.changed_files} />
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <EmptyList>{isChineseUi ? "还没有 output 记录。" : "No output records yet."}</EmptyList>
        )}
      </section>
      <section>
        <h3>{isChineseUi ? "产物内容" : "Artifact content"}</h3>
        {artifacts.length ? (
          <div className="fa-agent-team-output-list">
            {artifacts.map((artifact) => (
              <div className="fa-agent-team-output-row" key={artifact.artifact_id}>
                <div className="fa-agent-team-output-row-heading">
                  <span>{artifact.kind ?? "artifact"}</span>
                  <strong>{artifact.title ?? artifact.artifact_id}</strong>
                </div>
                {artifact.summary ? <p>{artifact.summary}</p> : null}
                <FieldList items={artifactPayloadItems(artifact, isChineseUi)} />
              </div>
            ))}
          </div>
        ) : (
          <EmptyList>{isChineseUi ? "还没有 artifact 记录。" : "No artifact records yet."}</EmptyList>
        )}
      </section>
    </>
  );
}

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
        <p>{shortText(task.planning_rationale || task.goal, isChineseUi ? "暂无拆解说明。" : "No split rationale yet.")}</p>
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
        <FieldList items={evidenceItems.length ? evidenceItems : fallbackEvidence} />
      </section>
      <section>
        <h3>{isChineseUi ? "需要注意" : "Needs attention"}</h3>
        <FieldList items={attentionItems.length ? attentionItems : taskAttentionItems(task, isChineseUi)} />
      </section>
    </div>
  );
}

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
    return <EmptyList>{isChineseUi ? "还没有协作方案。先生成 Mission 拆解。" : "No collaboration plan yet. Generate the mission breakdown first."}</EmptyList>;
  }

  return (
    <>
      <div className="fa-agent-team-task-list fa-agent-team-task-timeline">
        {tasks.map((task, index) => {
          const taskSummary = displayTaskSummary(task, isChineseUi);
          const title = displayTaskTitle(task, isChineseUi);
          const taskTooltip = [task.planning_rationale, taskSummary].filter(Boolean).join(" · ");
          const taskOutputs = outputsForTask(outputs, task);
          const taskArtifacts = artifactsForTask(artifacts, task, taskOutputs);
          const taskEvidence = taskOutputEvidence(taskOutputs);
          const taskRiskCount = uniqueStrings([...(task.risk_notes ?? []), ...taskOutputRisks(taskOutputs)]).length;
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
                  <div className="fa-agent-team-task-dependency-marker" aria-hidden="true">
                    <span>{taskDependencyLabel(task, isChineseUi)}</span>
                    <i />
                  </div>
                  <div>
                    <strong>{title}</strong>
                    <span>{taskSubtitle(task, isChineseUi)} · {userTaskStateLabel(state, isChineseUi)}</span>
                  </div>
                  <UserTaskStatusPill isChineseUi={isChineseUi} state={state} />
                </div>
                <p>{taskSummary}</p>
                <div className="fa-agent-team-task-result-summary fa-agent-team-task-return-preview">
                  <span>{isChineseUi ? "回传摘要" : "Returned summary"}</span>
                  <p>{taskResultSummary(task, isChineseUi, taskOutputs, taskArtifacts)}</p>
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
    </>
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
          <h2 {...tooltipProps(task.goal || displayTaskTitle(task, isChineseUi))}>{displayTaskTitle(task, isChineseUi)}</h2>
          <HelpText>
            {isChineseUi
              ? "这里默认只保留理解任务进展所需的信息。"
              : "This view keeps the default task progress details focused."}
          </HelpText>
        </div>
        <UserTaskStatusPill isChineseUi={isChineseUi} state={state} />
      </div>
      <TaskGuidedSections artifacts={returnedArtifacts} outputs={taskOutputs} task={task} tasks={taskList} />
      <details className="fa-agent-team-advanced-details">
        <summary>{isChineseUi ? "高级详情" : "Advanced details"}</summary>
        <div className="fa-agent-team-meta-grid">
          <div>
            <span>{isChineseUi ? "任务 ID" : "Task ID"}</span>
            <code {...tooltipProps(task.task_id)}>{task.task_id}</code>
          </div>
          <div>
            <span>{isChineseUi ? "分支线程" : "Branch thread"}</span>
            <code {...tooltipProps(branchThreadId || task.task_id)}>{branchThreadId || "—"}</code>
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
                <article className="fa-agent-team-artifact-card" key={artifact.artifact_id}>
                  <span>{artifact.kind ?? "artifact"}</span>
                  <strong>{artifact.title ?? artifact.artifact_id}</strong>
                  {artifact.summary ? <p>{artifact.summary}</p> : null}
                </article>
              ))}
            </div>
          ) : (
            <FieldList items={task.artifact_ids?.length ? task.artifact_ids : task.output_artifact_ids} />
          )}
        </section>
        <section>
          <h3>{isChineseUi ? "Output IDs" : "Output IDs"}</h3>
          <FieldList items={taskOutputs.map((output) => output.output_id)} />
        </section>
        <section>
          <h3>{isChineseUi ? "原始 output payload" : "Raw output payload"}</h3>
          <FieldList items={taskOutputs.map((output) => formatUnknown(output.metadata ?? output))} />
        </section>
        <section>
          <h3>{isChineseUi ? "原始 artifact payload" : "Raw artifact payload"}</h3>
          <FieldList items={returnedArtifacts.map((artifact) => formatUnknown(artifact.payload ?? artifact))} />
        </section>
        <section>
          <h3>{isChineseUi ? "原始运行状态" : "Raw run status"}</h3>
          <FieldList items={[...runStatusDetails(task), ...taskExecutionMetadataItems(task, isChineseUi)]} />
        </section>
        <TaskReturnedSections artifacts={returnedArtifacts} outputs={taskOutputs} />
        <section>
          <h3>{isChineseUi ? "变更文件" : "Changed files"}</h3>
          <FieldList items={task.changed_files} />
        </section>
      </details>
    </div>
  );
}

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
          <strong>{isChineseUi ? "计划任务与依赖" : "Planned work and dependencies"}</strong>
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
          {errorMessage(dispatchError, isChineseUi ? "生成协作方案失败。" : "Failed to generate the collaboration plan.")}
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
  const taskActionPending = runTask.isPending || retryTask.isPending || cancelTask.isPending;

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
              {retryTask.isPending ? (isChineseUi ? "重试中..." : "Retrying...") : isChineseUi ? "重试" : "Retry"}
            </button>
            <button
              className="fa-observability-preset is-danger"
              disabled={!canCancel || taskActionPending}
              onClick={() => cancelTask.mutate({ taskId: selectedTask.task_id })}
              type="button"
            >
              {cancelTask.isPending ? (isChineseUi ? "取消中..." : "Cancelling...") : isChineseUi ? "取消" : "Cancel"}
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
          {errorMessage(runTask.error, isChineseUi ? "执行失败。" : "Failed to run task.")}
        </div>
      ) : null}
      {retryTask.error ? (
        <div className="fa-inline-notice is-danger">
          {errorMessage(retryTask.error, isChineseUi ? "重试失败。" : "Failed to retry task.")}
        </div>
      ) : null}
      {cancelTask.error ? (
        <div className="fa-inline-notice is-danger">
          {errorMessage(cancelTask.error, isChineseUi ? "取消失败。" : "Failed to cancel task.")}
        </div>
      ) : null}
      <TaskDetail artifacts={artifacts} outputs={outputs} task={selectedTask} tasks={taskList} />
    </section>
  );
}
