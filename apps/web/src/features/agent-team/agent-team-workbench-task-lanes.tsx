import { Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import {
  DEFAULT_TASK_ROLES,
  compactTaskGoal,
  defaultTaskActionLabel,
  errorMessage,
  roleHint,
  roleLabel,
  taskGoalLabel,
} from "./agent-team-workbench-utils";
import { EmptyList, FieldList, HelpText, StatusPill } from "./agent-team-workbench-shared";
import { useCreateAgentTeamTask } from "./use-agent-team";
import type { AgentTeamArtifact, AgentTeamCreateTaskRequest, AgentTeamRole, AgentTeamTask } from "./types";

export function TaskBoard({
  rootThreadId,
  selectedTaskId,
  tasks,
  onSelectTask,
}: {
  rootThreadId: string;
  selectedTaskId: string | null;
  tasks: AgentTeamTask[];
  onSelectTask: (taskId: string) => void;
}) {
  const { isChineseUi } = useShellUi();
  if (!tasks.length) {
    return <EmptyList>{isChineseUi ? "还没有 Agent task。" : "No agent tasks yet."}</EmptyList>;
  }

  return (
    <div className="fa-agent-team-task-list">
      {tasks.map((task) => {
        const boundThreadId = task.child_thread_id ?? task.branch_id ?? "";
        const taskSummary = compactTaskGoal(task.goal || task.task_id);
        const taskTooltip = [roleHint(task.role, isChineseUi), taskSummary].filter(Boolean).join(" · ");
        return (
          <article
            className={`fa-agent-team-task-card ${selectedTaskId === task.task_id ? "is-selected" : ""}`.trim()}
            key={task.task_id}
            {...tooltipProps(taskTooltip)}
          >
            <button
              aria-label={`${roleLabel(task.role, isChineseUi)} · ${taskSummary}`}
              className="fa-agent-team-task-select"
              onClick={() => onSelectTask(task.task_id)}
              type="button"
            >
              <div className="fa-agent-team-task-topline">
                <div>
                  <strong>{roleLabel(task.role, isChineseUi)}</strong>
                </div>
                <StatusPill status={task.status} />
              </div>
              <div className="fa-agent-team-task-binding">
                <span>{isChineseUi ? "分支" : "Branch"}</span>
                <code>{boundThreadId || "—"}</code>
              </div>
            </button>
            {boundThreadId ? (
              <Link
                className="fa-route-state-link"
                params={{ conversationId: rootThreadId, threadId: boundThreadId }}
                to="/c/$conversationId/t/$threadId"
              >
                {isChineseUi ? "打开分支线程 →" : "Open branch thread →"}
              </Link>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

export function TaskDetail({ task, artifacts }: { task: AgentTeamTask | null; artifacts: AgentTeamArtifact[] }) {
  const { isChineseUi } = useShellUi();
  if (!task) {
    return (
      <EmptyList>
        {isChineseUi
          ? "在左侧选择一个任务，这里会显示它绑定的分支、范围、产出和风险。"
          : "Select a task on the left to see its branch, scope, outputs, and risks."}
      </EmptyList>
    );
  }
  const taskArtifacts = artifacts.filter(
    (artifact) => artifact.task_id === task.task_id || task.output_artifact_ids?.includes(artifact.artifact_id),
  );

  return (
    <div className="fa-agent-team-detail">
      <div className="fa-agent-team-detail-heading">
        <div>
          <span>{roleLabel(task.role, isChineseUi)}</span>
          <h2 {...tooltipProps(task.goal || task.task_id)}>{taskGoalLabel(task, isChineseUi)}</h2>
          <HelpText>{roleHint(task.role, isChineseUi)}</HelpText>
        </div>
        <StatusPill status={task.status} />
      </div>
      <div className="fa-agent-team-meta-grid">
        <div>
          <span>{isChineseUi ? "绑定分支" : "Bound branch"}</span>
          <code {...tooltipProps(task.child_thread_id ?? task.branch_id ?? task.task_id)}>
            {task.child_thread_id ?? task.branch_id ?? "—"}
          </code>
        </div>
      </div>
      <section>
        <h3>{isChineseUi ? "改动范围" : "Scope"}</h3>
        <FieldList items={task.scope} />
      </section>
      <section>
        <h3>{isChineseUi ? "改动文件" : "Changed files"}</h3>
        <FieldList items={task.changed_files} />
      </section>
      <section>
        <h3>{isChineseUi ? "验证证据" : "Verification"}</h3>
        {task.verification_summary ? <p>{task.verification_summary}</p> : <EmptyList>—</EmptyList>}
      </section>
      <section>
        <h3>{isChineseUi ? "风险备注" : "Risk notes"}</h3>
        <FieldList items={task.risk_notes} />
      </section>
      <section>
        <h3>{isChineseUi ? "产出证据" : "Outputs / Artifacts"}</h3>
        {taskArtifacts.length ? (
          <div className="fa-agent-team-artifact-list">
            {taskArtifacts.map((artifact) => (
              <article className="fa-agent-team-artifact-card" key={artifact.artifact_id}>
                <span>{artifact.kind ?? "artifact"}</span>
                <strong>{artifact.title ?? artifact.artifact_id}</strong>
                {artifact.summary ? <p>{artifact.summary}</p> : null}
              </article>
            ))}
          </div>
        ) : (
          <FieldList items={task.output_artifact_ids} />
        )}
      </section>
    </div>
  );
}

export function AddTaskPanel({ sessionId }: { sessionId: string }) {
  const { isChineseUi } = useShellUi();
  const createTask = useCreateAgentTeamTask(sessionId);
  const [role, setRole] = useState<AgentTeamRole>("frontend_executor");
  const [goal, setGoal] = useState("");
  const [scope, setScope] = useState("apps/web/src/features/agent-team/**\napps/web/src/pages/agent-team/**");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextGoal = goal.trim();
    if (!nextGoal || createTask.isPending) return;
    const request: AgentTeamCreateTaskRequest = {
      role,
      goal: nextGoal,
      scope: scope
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
    };
    await createTask.mutateAsync(request);
    setGoal("");
  }

  return (
    <form className="fa-agent-team-add-task" onSubmit={handleSubmit}>
      <div>
        <span className="fa-agent-team-section-kicker">{isChineseUi ? "可选" : "Optional"}</span>
        <strong>{isChineseUi ? "手动追加任务" : "Add one custom task"}</strong>
        <HelpText>
          {isChineseUi
            ? "默认任务覆盖常见协作流程；只有需要额外分工时再手动追加。"
            : "Default tasks cover the usual workflow. Add a custom task only when another lane is needed."}
        </HelpText>
      </div>
      <label className="fa-agent-team-field">
        <span>{isChineseUi ? "角色" : "Role"}</span>
        <select value={role} onChange={(event) => setRole(event.target.value as AgentTeamRole)}>
          {DEFAULT_TASK_ROLES.map((item) => (
            <option key={item} value={item}>
              {roleLabel(item, isChineseUi)}
            </option>
          ))}
        </select>
      </label>
      <label className="fa-agent-team-field">
        <span>{isChineseUi ? "目标" : "Goal"}</span>
        <input
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder={isChineseUi ? "例如：单独检查移动端布局" : "Example: separately check mobile layout"}
        />
      </label>
      <label className="fa-agent-team-field">
        <span>{isChineseUi ? "改动范围（每行一个）" : "Scope (one per line)"}</span>
        <textarea value={scope} onChange={(event) => setScope(event.target.value)} />
      </label>
      {createTask.error ? (
        <div className="fa-inline-notice is-danger">
          {errorMessage(createTask.error, isChineseUi ? "创建 task 失败。" : "Failed to create task.")}
        </div>
      ) : null}
      <button className="fa-observability-preset" disabled={!goal.trim() || createTask.isPending} type="submit">
        {createTask.isPending
          ? isChineseUi
            ? "添加中..."
            : "Adding..."
          : isChineseUi
            ? goal.trim()
              ? "添加任务"
              : "填写目标后添加"
            : goal.trim()
              ? "Add task"
              : "Fill goal to add"}
      </button>
    </form>
  );
}

export function TaskLanesPanel({
  defaultTasksReady,
  dispatchError,
  dispatchPending,
  onCreateDefaultTasks,
  onSelectTask,
  rootThreadId,
  selectedTaskId,
  sessionId,
  taskCount,
  tasks,
}: {
  defaultTasksReady: boolean;
  dispatchError: Error | null;
  dispatchPending: boolean;
  onCreateDefaultTasks: () => void;
  onSelectTask: (taskId: string) => void;
  rootThreadId: string;
  selectedTaskId: string | null;
  sessionId: string;
  taskCount: number;
  tasks: AgentTeamTask[];
}) {
  const { isChineseUi } = useShellUi();

  return (
    <section className="fa-agent-team-panel">
      <div className="fa-agent-team-panel-header">
        <div>
          <span>{isChineseUi ? "第二步 · 任务队列" : "Step 2 · Task queue"}</span>
          <strong>{isChineseUi ? "Agent 任务" : "Agent tasks"}</strong>
        </div>
        <button
          className="fa-observability-preset"
          disabled={defaultTasksReady || dispatchPending}
          onClick={onCreateDefaultTasks}
          type="button"
        >
          {defaultTaskActionLabel({
            isChineseUi,
            isPending: dispatchPending,
            defaultTasksReady,
            taskCount,
          })}
        </button>
      </div>
      <HelpText>
        {isChineseUi
          ? "默认任务会自动建立规划、后端、前端、测试、审查、验证 6 条协作分支。"
          : "Default tasks create six collaboration branches: planning, backend, frontend, testing, review, and verification."}
      </HelpText>
      {dispatchError ? (
        <div className="fa-inline-notice is-danger">
          {errorMessage(dispatchError, isChineseUi ? "调度默认任务失败。" : "Failed to dispatch default tasks.")}
        </div>
      ) : null}
      <TaskBoard
        rootThreadId={rootThreadId}
        selectedTaskId={selectedTaskId}
        tasks={tasks}
        onSelectTask={onSelectTask}
      />
      <AddTaskPanel sessionId={sessionId} />
    </section>
  );
}

export function TaskDetailPanel({ artifacts, selectedTask }: { artifacts: AgentTeamArtifact[]; selectedTask: AgentTeamTask | null }) {
  const { isChineseUi } = useShellUi();

  return (
    <section className="fa-agent-team-panel">
      <div className="fa-agent-team-panel-header">
        <div>
          <span>{isChineseUi ? "第三步 · 分支绑定" : "Step 3 · Branch binding"}</span>
          <strong>{isChineseUi ? "任务详情与分支" : "Task detail and branch"}</strong>
          <HelpText>
            {isChineseUi
              ? "点左侧任务后，确认它对应的分支线程、改动范围、验证结果和风险。"
              : "Click a task on the left to confirm its branch thread, scope, verification, and risks."}
          </HelpText>
        </div>
      </div>
      <TaskDetail artifacts={artifacts} task={selectedTask} />
    </section>
  );
}
