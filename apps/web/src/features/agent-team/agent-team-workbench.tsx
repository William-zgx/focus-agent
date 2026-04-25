import { Link } from "@tanstack/react-router";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useConversations } from "@/features/conversations/use-conversations";
import { tooltipProps } from "@/shared/ui/tooltip";

import {
  useAgentTeamMergeProposal,
  useAgentTeamSession,
  useAgentTeamSessions,
  useCreateAgentTeamSession,
  useCreateAgentTeamTask,
  useDispatchAgentTeamSession,
} from "./use-agent-team";
import type {
  AgentTeamArtifact,
  AgentTeamCreateTaskRequest,
  AgentTeamMergeBundle,
  AgentTeamRole,
  AgentTeamSession,
  AgentTeamSessionView,
  AgentTeamTask,
} from "./types";

const DEFAULT_TASK_ROLES: AgentTeamRole[] = [
  "planner",
  "backend_executor",
  "frontend_executor",
  "test_engineer",
  "reviewer",
  "verifier",
];

const STATUS_TONES: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  completed: "success",
  done: "success",
  awaiting_review: "warning",
  blocked: "warning",
  merging: "warning",
  failed: "danger",
  cancelled: "danger",
  planning: "neutral",
  pending: "neutral",
  running: "neutral",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function titleFromGoal(goal: string) {
  const normalized = goal.trim().replace(/\s+/g, " ");
  return normalized.length > 34 ? `${normalized.slice(0, 34)}…` : normalized || "Agent Team Session";
}

function roleLabel(role: string, isChineseUi: boolean) {
  if (!isChineseUi) return role.replaceAll("_", " ");
  const labels: Record<string, string> = {
    planner: "规划",
    architect: "架构",
    backend_executor: "后端执行",
    frontend_executor: "前端执行",
    test_engineer: "测试",
    reviewer: "审查",
    verifier: "验证",
    writer: "文档",
  };
  return labels[role] ?? role.replaceAll("_", " ");
}

function roleHint(role: string, isChineseUi: boolean) {
  if (!isChineseUi) {
    const hints: Record<string, string> = {
      planner: "Breaks the goal into lanes",
      backend_executor: "Builds service / API work",
      frontend_executor: "Builds UI / interaction work",
      test_engineer: "Locks behavior with tests",
      reviewer: "Finds risks before merge",
      verifier: "Checks completion evidence",
      writer: "Documents the result",
    };
    return hints[role] ?? "Agent task lane";
  }

  const hints: Record<string, string> = {
    planner: "拆目标和边界",
    backend_executor: "实现服务 / API",
    frontend_executor: "实现页面 / 交互",
    test_engineer: "补测试和用例",
    reviewer: "审查风险",
    verifier: "验证完成证据",
    writer: "沉淀文档",
  };
  return hints[role] ?? "Agent 分工";
}

function taskGoalLabel(task: AgentTeamTask, isChineseUi: boolean) {
  const labels: Record<string, string> = isChineseUi
    ? {
        planner: "拆解目标与边界",
        backend_executor: "实现服务与 API",
        frontend_executor: "实现页面与交互",
        test_engineer: "补齐测试证据",
        reviewer: "审查回归与风险",
        verifier: "验证完成状态",
        writer: "整理协作文档",
      }
    : {
        planner: "Plan scope and boundaries",
        backend_executor: "Build service and API",
        frontend_executor: "Build UI and interactions",
        test_engineer: "Add test evidence",
        reviewer: "Review regressions and risks",
        verifier: "Verify completion",
        writer: "Document the collaboration",
      };

  return labels[task.role] ?? titleFromGoal(task.goal || task.task_id);
}

function statusLabel(status: string, isChineseUi: boolean) {
  if (!isChineseUi) return status.replaceAll("_", " ");
  const labels: Record<string, string> = {
    awaiting_review: "待审查",
    blocked: "阻塞",
    cancelled: "已取消",
    completed: "已完成",
    done: "已完成",
    failed: "失败",
    merging: "汇总中",
    pending: "待开始",
    planning: "规划中",
    running: "执行中",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function normalizeSessionView(data: AgentTeamSession | AgentTeamSessionView | undefined): AgentTeamSessionView | null {
  if (!data) return null;
  if ("session" in data) {
    return {
      session: data.session,
      tasks: data.tasks ?? [],
      artifacts: data.artifacts ?? [],
      merge_bundle: data.merge_bundle ?? null,
    };
  }

  const dataRecord = data as AgentTeamSession & Record<string, unknown>;
  return {
    session: data,
    tasks: Array.isArray(dataRecord.tasks) ? (dataRecord.tasks as AgentTeamTask[]) : [],
    artifacts: Array.isArray(dataRecord.artifacts) ? (dataRecord.artifacts as AgentTeamArtifact[]) : [],
    merge_bundle: isRecord(dataRecord.merge_bundle)
      ? (dataRecord.merge_bundle as unknown as AgentTeamMergeBundle)
      : null,
  };
}

function normalizeMergeBundle(
  data: AgentTeamMergeBundle | AgentTeamSessionView | undefined,
): AgentTeamMergeBundle | null {
  if (!data) return null;
  if ("session" in data) return data.merge_bundle ?? null;
  return data;
}

function StatusPill({ status }: { status: string }) {
  const { isChineseUi } = useShellUi();
  const tone = STATUS_TONES[status] ?? "neutral";
  return <span className={`fa-agent-team-pill is-${tone}`}>{statusLabel(status, isChineseUi)}</span>;
}

function EmptyList({ children }: { children: string }) {
  return <div className="fa-agent-team-empty">{children}</div>;
}

function AgentTeamRouteTabs({ isChineseUi }: { isChineseUi: boolean }) {
  return (
    <nav
      aria-label={isChineseUi ? "Agent 工作台导航" : "Agent workbench navigation"}
      className="fa-trajectory-workbench-tabs fa-observability-route-tabs"
    >
      <Link
        className="fa-trajectory-workbench-tab fa-observability-route-tab"
        to="/observability/overview"
        {...tooltipProps(isChineseUi ? "查看趋势、热点和全局健康状态" : "View trends, hotspots, and global health")}
      >
        <span>{isChineseUi ? "全局诊断" : "Global health"}</span>
      </Link>
      <Link
        className="fa-trajectory-workbench-tab fa-observability-route-tab"
        to="/agent/governance"
        {...tooltipProps(isChineseUi ? "查看记忆、工具和模型路由治理" : "View memory, tools, and routing governance")}
      >
        <span>{isChineseUi ? "Agent 治理" : "Agent governance"}</span>
      </Link>
      <Link
        className="fa-trajectory-workbench-tab fa-observability-route-tab is-active"
        to="/agent-team"
        {...tooltipProps(isChineseUi ? "多 Agent 分工协作工作台" : "Multi-agent collaboration workbench")}
      >
        <span>{isChineseUi ? "Agent Team" : "Agent Team"}</span>
      </Link>
    </nav>
  );
}

function FieldList({ items }: { items?: string[] }) {
  if (!items?.length) return <EmptyList>—</EmptyList>;
  return (
    <ul className="fa-agent-team-list">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function HelpText({ children }: { children: string }) {
  const { isChineseUi } = useShellUi();
  return (
    <span
      aria-label={isChineseUi ? "说明" : "Help"}
      className="fa-agent-team-help-tip"
      role="img"
      tabIndex={0}
      {...tooltipProps(children)}
    />
  );
}

function WorkflowGuide({ compact = false }: { compact?: boolean }) {
  const { isChineseUi } = useShellUi();
  const summary = isChineseUi
    ? "把一个大目标拆给多个 Agent，并保留可回溯证据。"
    : "Split one large goal across agents while keeping traceable evidence.";
  const steps = isChineseUi
    ? [
        ["1", "写目标", "说明这组 Agent 要一起完成什么"],
        ["2", "生成任务", "自动拆成规划、执行、测试、审查、验证分支"],
        ["3", "进分支做事", "每个 Agent 在线程里留下产出和证据"],
        ["4", "汇总合并", "把改动、风险、验证证据收束成建议"],
      ]
    : [
        ["1", "Write goal", "Describe what the agents should finish together"],
        ["2", "Create tasks", "Split into planning, execution, test, review, and verification branches"],
        ["3", "Work in branches", "Each agent leaves outputs and evidence in its thread"],
        ["4", "Merge summary", "Collect changes, risks, and evidence into a recommendation"],
      ];

  return (
    <section className={`fa-agent-team-guide ${compact ? "is-compact" : ""}`.trim()}>
      <div className="fa-agent-team-guide-heading">
        <span>{isChineseUi ? "它是做什么的" : "What this does"}</span>
        <strong {...tooltipProps(summary)}>
          {isChineseUi ? "4 步完成多 Agent 协作" : "Finish multi-agent work in 4 steps"}
        </strong>
      </div>
      <div className="fa-agent-team-step-strip">
        {steps.map(([index, title, description]) => (
          <div className="fa-agent-team-step" key={index} {...tooltipProps(description)}>
            <span>{index}</span>
            <strong>{title}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function StatusLegend() {
  const { isChineseUi } = useShellUi();
  const legendText = isChineseUi
    ? "待开始：任务已创建但未执行；执行中：Agent 正在分支工作；已完成：产出和验证已回传；阻塞：需要处理风险或缺口。"
    : "Pending: task exists but has not run; Running: agent is working in a branch; Completed: outputs and evidence are returned; Blocked: risk or gap needs attention.";
  return (
    <span className="fa-agent-team-legend-chip" {...tooltipProps(legendText)}>
      {isChineseUi ? "状态图例" : "Status legend"}
    </span>
  );
}

function RecentSessionsPanel({ rootThreadId }: { rootThreadId: string }) {
  const { isChineseUi } = useShellUi();
  const recentSessions = useAgentTeamSessions({
    limit: 5,
    root_thread_id: rootThreadId.trim() || undefined,
  });
  const sessions = recentSessions.data?.items ?? [];

  return (
    <section className="fa-agent-team-panel fa-agent-team-recent-panel">
      <div className="fa-agent-team-panel-header">
        <div>
          <span>{isChineseUi ? "快速返回" : "Quick return"}</span>
          <strong>{isChineseUi ? "最近 Agent Team" : "Recent Agent Teams"}</strong>
        </div>
      </div>
      {recentSessions.isLoading ? (
        <EmptyList>{isChineseUi ? "正在加载最近协作空间..." : "Loading recent workspaces..."}</EmptyList>
      ) : recentSessions.error ? (
        <div className="fa-inline-notice is-danger">
          {errorMessage(recentSessions.error, isChineseUi ? "最近协作空间加载失败。" : "Failed to load recent workspaces.")}
        </div>
      ) : sessions.length ? (
        <div className="fa-agent-team-recent-list">
          {sessions.map((session) => (
            <Link
              className="fa-agent-team-recent-item"
              key={session.session_id}
              params={{ sessionId: session.session_id }}
              to="/agent-team/$sessionId"
              {...tooltipProps(session.goal)}
            >
              <span>{statusLabel(session.status, isChineseUi)}</span>
              <strong>{session.title ? titleFromGoal(session.title) : session.session_id}</strong>
            </Link>
          ))}
        </div>
      ) : (
        <EmptyList>
          {rootThreadId.trim()
            ? isChineseUi
              ? "当前主线程还没有 Agent Team。"
              : "No Agent Team exists for this root thread yet."
            : isChineseUi
              ? "还没有 Agent Team。创建后会出现在这里。"
              : "No Agent Team yet. New workspaces will appear here."}
        </EmptyList>
      )}
    </section>
  );
}

function CreateSessionPanel() {
  const { isChineseUi } = useShellUi();
  const conversationsQuery = useConversations();
  const createSession = useCreateAgentTeamSession();
  const [goal, setGoal] = useState("");
  const [title, setTitle] = useState("");
  const [rootThreadId, setRootThreadId] = useState(() => {
    if (typeof window === "undefined") return "";
    return new URLSearchParams(window.location.search).get("root_thread_id") ?? "";
  });
  const [manualRootEntry, setManualRootEntry] = useState(false);
  const conversations = useMemo(() => {
    const activeConversations = [...(conversationsQuery.data?.conversations ?? [])]
      .filter((conversation) => !conversation.is_archived)
      .sort((left, right) => {
        const leftTime = Date.parse(left.updated_at ?? left.created_at ?? "");
        const rightTime = Date.parse(right.updated_at ?? right.created_at ?? "");
        return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
      });
    const recentConversations = activeConversations.slice(0, 12);
    const selected = rootThreadId
      ? activeConversations.find((conversation) => conversation.root_thread_id === rootThreadId)
      : null;

    if (!selected || recentConversations.some((conversation) => conversation.root_thread_id === selected.root_thread_id)) {
      return recentConversations;
    }

    return [selected, ...recentConversations.slice(0, 11)];
  }, [conversationsQuery.data?.conversations, rootThreadId]);
  const selectedConversation = conversations.find((conversation) => conversation.root_thread_id === rootThreadId);
  const rootSelectValue = manualRootEntry || (rootThreadId && !selectedConversation) ? "__manual__" : rootThreadId;

  useEffect(() => {
    if (rootThreadId || !conversations.length) return;
    setRootThreadId(conversations[0].root_thread_id);
  }, [conversations, rootThreadId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextGoal = goal.trim();
    const nextRootThreadId = rootThreadId.trim();
    if (!nextGoal || !nextRootThreadId || createSession.isPending) return;
    const response = await createSession.mutateAsync({
      goal: nextGoal,
      title: title.trim() || titleFromGoal(nextGoal),
      root_thread_id: nextRootThreadId,
    });
    const session = "session" in response ? response.session : response;
    window.history.pushState(null, "", `/app/agent-team/${encodeURIComponent(session.session_id)}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
  const createHeroHelp = isChineseUi
    ? "先写一个大目标，再生成角色任务，把每个 Agent 的分支、产出、风险和验证证据集中管理。"
    : "Enter one large goal, create role tasks, and manage branches, outputs, risks, and evidence in one place.";

  return (
    <div className="fa-agent-team-layout is-create">
      <div className="fa-agent-team-create-copy">
        <section className="fa-observability-hero fa-agent-team-hero">
          <div className="fa-observability-hero-copy">
            <span className="fa-observability-kicker">Agent Team Workbench</span>
            <h1>{isChineseUi ? "创建 Agent Team 协作空间" : "Create an Agent Team workspace"}</h1>
            <p className="fa-observability-hero-text" {...tooltipProps(createHeroHelp)}>
              {isChineseUi ? "多 Agent 协作控制台" : "Multi-agent collaboration console"}
            </p>
            <AgentTeamRouteTabs isChineseUi={isChineseUi} />
          </div>
        </section>

        <WorkflowGuide />

        <section className="fa-agent-team-panel fa-agent-team-roles-panel">
          <div className="fa-agent-team-panel-header">
            <div>
              <span>{isChineseUi ? "MVP 默认角色" : "MVP default roles"}</span>
              <strong>{isChineseUi ? "固定角色，可审计产出" : "Fixed roles, auditable outputs"}</strong>
            </div>
          </div>
          <div className="fa-agent-team-role-grid">
            {DEFAULT_TASK_ROLES.map((role) => (
              <div className="fa-agent-team-role-chip" key={role} {...tooltipProps(roleHint(role, isChineseUi))}>
                <strong>{roleLabel(role, isChineseUi)}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="fa-agent-team-create-actions">
        <form className="fa-agent-team-panel fa-agent-team-create-form" onSubmit={handleSubmit}>
          <div className="fa-agent-team-panel-header">
            <div>
              <span>{isChineseUi ? "第一步" : "Step 1"}</span>
              <strong>{isChineseUi ? "描述协作目标" : "Describe the collaboration goal"}</strong>
            </div>
          </div>
          <label className="fa-agent-team-field">
            <span>{isChineseUi ? "主线程" : "Root thread"}</span>
            <select
              value={rootSelectValue}
              onChange={(event) => {
                const nextValue = event.target.value;
                if (nextValue === "__manual__") {
                  setManualRootEntry(true);
                  return;
                }
                setManualRootEntry(false);
                setRootThreadId(nextValue);
              }}
            >
              <option value="">
                {conversationsQuery.isLoading
                  ? isChineseUi
                    ? "正在读取对话..."
                    : "Loading conversations..."
                  : isChineseUi
                    ? "选择一个已有对话"
                    : "Select an existing conversation"}
              </option>
              {conversations.map((conversation) => (
                <option key={conversation.root_thread_id} value={conversation.root_thread_id}>
                  {conversation.title ? titleFromGoal(conversation.title) : conversation.root_thread_id}
                </option>
              ))}
              <option value="__manual__">{isChineseUi ? "手动输入线程 ID" : "Enter thread ID manually"}</option>
            </select>
            {manualRootEntry || (rootThreadId && !selectedConversation) ? (
              <input
                value={rootThreadId}
                onChange={(event) => setRootThreadId(event.target.value)}
                placeholder="thread_..."
              />
            ) : null}
            <HelpText>
              {isChineseUi
                ? "默认使用当前对话；没有当前对话时可从已有对话中选择。只有调试或粘贴外部线程时才需要手动输入。"
                : "Defaults to the current conversation. If there is no current conversation, choose an existing one. Manual entry is only for debugging or external thread IDs."}
            </HelpText>
          </label>
          <label className="fa-agent-team-field">
            <span>{isChineseUi ? "标题（可选）" : "Title (optional)"}</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={isChineseUi ? "默认使用目标摘要" : "Defaults to goal summary"}
            />
          </label>
          <label className="fa-agent-team-field">
            <span>{isChineseUi ? "协作目标" : "Team goal"}</span>
            <textarea
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder={
                isChineseUi
                  ? "例如：实现 Agent Team Workbench MVP，并补齐验证证据。"
                  : "Example: Implement the Agent Team Workbench MVP and capture verification evidence."
              }
            />
            <HelpText>
              {isChineseUi
                ? "写清楚这组 Agent 要一起完成什么。创建后可以一键生成规划、执行、测试、审查、验证任务。"
                : "Describe what the agent team should accomplish together. After creation, generate planning, execution, test, review, and verification tasks."}
            </HelpText>
          </label>
          {createSession.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(createSession.error, isChineseUi ? "创建失败。" : "Failed to create session.")}
            </div>
          ) : null}
          <button
            className="fa-observability-preset is-primary"
            disabled={!goal.trim() || !rootThreadId.trim() || createSession.isPending}
            type="submit"
          >
            {createSession.isPending
              ? isChineseUi
                ? "创建中..."
                : "Creating..."
              : isChineseUi
                ? "创建协作空间"
                : "Create session"}
          </button>
          {!goal.trim() || !rootThreadId.trim() ? (
            <HelpText>
              {isChineseUi
                ? "填写主线程 ID 和协作目标后即可创建。"
                : "Fill the root thread ID and team goal to create the workspace."}
            </HelpText>
          ) : null}
        </form>

        <RecentSessionsPanel rootThreadId={rootThreadId} />
      </div>
    </div>
  );
}

function TaskBoard({
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
        const taskTooltip = [roleHint(task.role, isChineseUi), task.goal].filter(Boolean).join(" · ");
        return (
          <article
            className={`fa-agent-team-task-card ${selectedTaskId === task.task_id ? "is-selected" : ""}`.trim()}
            key={task.task_id}
            {...tooltipProps(taskTooltip)}
          >
            <button
              aria-label={`${roleLabel(task.role, isChineseUi)} · ${task.goal || task.task_id}`}
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

function TaskDetail({ task, artifacts }: { task: AgentTeamTask | null; artifacts: AgentTeamArtifact[] }) {
  const { isChineseUi } = useShellUi();
  if (!task) {
    return <EmptyList>{isChineseUi ? "在左侧选择一个任务，这里会显示它绑定的分支、范围、产出和风险。" : "Select a task on the left to see its branch, scope, outputs, and risks."}</EmptyList>;
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
          <span>Task ID</span>
          <code>{task.task_id}</code>
        </div>
        <div>
          <span>{isChineseUi ? "Branch / Thread" : "Branch / Thread"}</span>
          <code>{task.child_thread_id ?? task.branch_id ?? "—"}</code>
        </div>
      </div>
      <section>
        <h3>{isChineseUi ? "Scope" : "Scope"}</h3>
        <FieldList items={task.scope} />
      </section>
      <section>
        <h3>{isChineseUi ? "Changed files" : "Changed files"}</h3>
        <FieldList items={task.changed_files} />
      </section>
      <section>
        <h3>{isChineseUi ? "Verification" : "Verification"}</h3>
        {task.verification_summary ? <p>{task.verification_summary}</p> : <EmptyList>—</EmptyList>}
      </section>
      <section>
        <h3>{isChineseUi ? "Risk notes" : "Risk notes"}</h3>
        <FieldList items={task.risk_notes} />
      </section>
      <section>
        <h3>{isChineseUi ? "Outputs / Artifacts" : "Outputs / Artifacts"}</h3>
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

function AddTaskPanel({ sessionId }: { sessionId: string }) {
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
      scope: scope.split("\n").map((item) => item.trim()).filter(Boolean),
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
        <span>{isChineseUi ? "Scope（每行一个）" : "Scope (one per line)"}</span>
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

function MergeBundleCard({
  bundle,
  pendingBundle,
  onGenerate,
  isGenerating,
  error,
  canGenerate,
}: {
  bundle: AgentTeamMergeBundle | null;
  pendingBundle: AgentTeamMergeBundle | null;
  onGenerate: () => void;
  isGenerating: boolean;
  error: Error | null;
  canGenerate: boolean;
}) {
  const { isChineseUi } = useShellUi();
  const activeBundle = pendingBundle ?? bundle;

  return (
    <section className="fa-agent-team-panel fa-agent-team-merge-card">
      <div className="fa-agent-team-panel-header">
        <div>
          <span>{isChineseUi ? "最终动作 · Merge Bundle" : "Final action · Merge Bundle"}</span>
          <strong>{isChineseUi ? "受控合并摘要" : "Controlled merge summary"}</strong>
          <HelpText>
            {isChineseUi
              ? "把各任务的改动、证据、风险和未决问题收束成一次可审查的合并建议。"
              : "Collect task changes, evidence, risks, and open questions into one reviewable merge recommendation."}
          </HelpText>
        </div>
        {activeBundle?.recommended_next_action ? (
          <StatusPill status={activeBundle.recommended_next_action} />
        ) : null}
      </div>
      {activeBundle ? (
        <div className="fa-agent-team-merge-grid">
          <p>{activeBundle.summary || (isChineseUi ? "暂无摘要。" : "No summary yet.")}</p>
          <div>
            <h3>{isChineseUi ? "Key findings" : "Key findings"}</h3>
            <FieldList items={activeBundle.key_findings} />
          </div>
          <div>
            <h3>{isChineseUi ? "Changed files" : "Changed files"}</h3>
            <FieldList items={activeBundle.changed_files} />
          </div>
          <div>
            <h3>{isChineseUi ? "Test evidence" : "Test evidence"}</h3>
            <FieldList items={activeBundle.test_evidence} />
          </div>
          <div>
            <h3>{isChineseUi ? "Open questions" : "Open questions"}</h3>
            <FieldList items={activeBundle.open_questions} />
          </div>
          <div>
            <h3>{isChineseUi ? "Risks" : "Risks"}</h3>
            <FieldList items={activeBundle.risk_items} />
          </div>
        </div>
      ) : (
        <EmptyList>{isChineseUi ? "还没有生成协作汇总。" : "No collaboration summary generated yet."}</EmptyList>
      )}
      {error ? <div className="fa-inline-notice is-danger">{error.message}</div> : null}
      <button className="fa-observability-preset is-primary" disabled={!canGenerate || isGenerating} onClick={onGenerate} type="button">
        {isGenerating
          ? isChineseUi
            ? "生成中..."
            : "Generating..."
          : !canGenerate
            ? isChineseUi
              ? "先生成任务再汇总"
              : "Create tasks before summary"
            : isChineseUi
              ? "生成协作汇总"
              : "Generate collaboration summary"}
      </button>
    </section>
  );
}

export function AgentTeamWorkbench({ sessionId }: { sessionId: string | null }) {
  const { isChineseUi } = useShellUi();
  const sessionQuery = useAgentTeamSession(sessionId);
  const dispatchSession = useDispatchAgentTeamSession(sessionId);
  const mergeProposal = useAgentTeamMergeProposal(sessionId);
  const view = normalizeSessionView(sessionQuery.data);
  const tasks = view?.tasks ?? [];
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const selectedTask = useMemo(() => {
    if (!tasks.length) return null;
    return tasks.find((task) => task.task_id === selectedTaskId) ?? tasks[0];
  }, [selectedTaskId, tasks]);
  const pendingBundle = normalizeMergeBundle(mergeProposal.data);

  if (!sessionId) return <CreateSessionPanel />;

  if (sessionQuery.isLoading) {
    return (
      <div className="fa-route-state">
        <div className="fa-route-state-card">
          <p className="fa-route-state-title">{isChineseUi ? "正在加载 Agent Team..." : "Loading Agent Team..."}</p>
        </div>
      </div>
    );
  }

  if (sessionQuery.error || !view) {
    return (
      <div className="fa-route-state">
        <div className="fa-route-state-card">
          <p className="fa-route-state-title">
            {isChineseUi ? "无法加载 Agent Team Session" : "Unable to load Agent Team session"}
          </p>
          <p>{errorMessage(sessionQuery.error, isChineseUi ? "返回的数据为空。" : "The response was empty.")}</p>
          <Link className="fa-route-state-link" to="/agent-team">
            {isChineseUi ? "创建新的 Session" : "Create a new session"}
          </Link>
        </div>
      </div>
    );
  }

  const session = view.session;
  const changedFiles = Array.from(new Set(tasks.flatMap((task) => task.changed_files ?? [])));
  const outputArtifactIds = Array.from(new Set(tasks.flatMap((task) => task.output_artifact_ids ?? [])));
  const taskRoles = new Set(tasks.map((task) => task.role));
  const defaultTasksReady = DEFAULT_TASK_ROLES.every((role) => taskRoles.has(role));
  const displayTitle = session.title && session.title !== session.goal ? session.title : titleFromGoal(session.goal);
  const sessionHeroHelp = isChineseUi
    ? "这是协作控制台：左侧拆任务，中间看分支绑定，右侧看产出风险，底部生成合并建议。"
    : "This is the collaboration console: tasks on the left, branch binding in the middle, outputs and risks on the right, merge guidance at the bottom.";
  const nextStep = !tasks.length
    ? {
        label: isChineseUi ? "生成默认任务" : "Create default tasks",
        help: isChineseUi
          ? "生成 6 个默认任务，让规划、执行、测试、审查、验证各自有独立分支。"
          : "Create 6 default tasks so planning, execution, testing, review, and verification each get their own branch.",
      }
    : outputArtifactIds.length || changedFiles.length
      ? {
          label: isChineseUi ? "生成协作汇总" : "Generate merge summary",
          help: isChineseUi
            ? "把产出、风险和验证证据收束成可审查建议。"
            : "Collect outputs, risks, and evidence into a reviewable recommendation.",
        }
      : {
          label: isChineseUi ? "打开分支线程执行" : "Open branch threads",
          help: isChineseUi
            ? "打开任务线程，让对应 Agent 在分支里工作；产出会回到这里汇总。"
            : "Open task threads and let each agent work in its branch; outputs will roll back up here.",
        };

  return (
    <div className="fa-agent-team-layout">
      <section className="fa-observability-hero fa-agent-team-hero">
        <div className="fa-observability-hero-copy">
          <span className="fa-observability-kicker">Agent Team Workbench</span>
          <h1>{displayTitle || session.session_id}</h1>
          <p className="fa-observability-hero-text fa-agent-team-goal-line" {...tooltipProps(session.goal)}>
            {session.goal}
          </p>
          <HelpText>{sessionHeroHelp}</HelpText>
          <AgentTeamRouteTabs isChineseUi={isChineseUi} />
        </div>
        <div className="fa-agent-team-session-meta">
          <StatusPill status={session.status} />
          <div>
            <span>Session</span>
            <code>{session.session_id}</code>
          </div>
          <div>
            <span>{isChineseUi ? "主线程" : "Root thread"}</span>
            <Link
              className="fa-route-state-link"
              params={{ conversationId: session.root_thread_id, threadId: session.root_thread_id }}
              to="/c/$conversationId/t/$threadId"
            >
              {session.root_thread_id}
            </Link>
          </div>
          <StatusLegend />
        </div>
      </section>

      <WorkflowGuide compact />

      <div className="fa-agent-team-summary-grid">
        <div
          className="fa-observability-stat-card"
          {...tooltipProps(isChineseUi ? "当前协作空间里的 Agent 角色任务数量。" : "Number of agent role tasks in this workspace.")}
        >
          <span>{isChineseUi ? "Tasks" : "Tasks"}</span>
          <strong>{tasks.length}</strong>
        </div>
        <div
          className="fa-observability-stat-card"
          {...tooltipProps(isChineseUi ? "各任务回传的产出或证据引用数量。" : "Number of output or evidence references returned by tasks.")}
        >
          <span>{isChineseUi ? "Outputs" : "Outputs"}</span>
          <strong>{outputArtifactIds.length}</strong>
        </div>
        <div
          className="fa-observability-stat-card"
          {...tooltipProps(isChineseUi ? "跨任务汇总出来的改动文件数量。" : "Number of changed files aggregated across tasks.")}
        >
          <span>{isChineseUi ? "Changed files" : "Changed files"}</span>
          <strong>{changedFiles.length}</strong>
        </div>
      </div>

      <div className="fa-agent-team-next-step">
        <span>{isChineseUi ? "使用提示" : "Guide"}</span>
        <strong {...tooltipProps(nextStep.help)}>{nextStep.label}</strong>
      </div>

      <div className="fa-agent-team-workbench-grid">
        <section className="fa-agent-team-panel">
          <div className="fa-agent-team-panel-header">
            <div>
              <span>{isChineseUi ? "第二步 · 任务队列" : "Step 2 · Task queue"}</span>
              <strong>{isChineseUi ? "Agent Task Board" : "Agent Task Board"}</strong>
            </div>
            <button
              className="fa-observability-preset"
              disabled={defaultTasksReady || dispatchSession.isPending}
              onClick={() => dispatchSession.mutate({ create_branches: true })}
              type="button"
            >
              {dispatchSession.isPending
                ? isChineseUi
                  ? "调度中..."
                  : "Dispatching..."
                : defaultTasksReady
                  ? isChineseUi
                    ? "默认任务已就绪"
                    : "Default tasks ready"
                : tasks.length
                  ? isChineseUi
                    ? "补齐默认任务"
                    : "Fill default tasks"
                  : isChineseUi
                    ? "生成 6 个默认任务"
                    : "Create 6 default tasks"}
            </button>
          </div>
          <HelpText>
            {isChineseUi
              ? "默认任务会自动建立规划、后端、前端、测试、审查、验证 6 条协作分支。"
              : "Default tasks create six collaboration branches: planning, backend, frontend, testing, review, and verification."}
          </HelpText>
          {dispatchSession.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(dispatchSession.error, isChineseUi ? "调度默认任务失败。" : "Failed to dispatch default tasks.")}
            </div>
          ) : null}
          <TaskBoard
            rootThreadId={session.root_thread_id}
            selectedTaskId={selectedTask?.task_id ?? null}
            tasks={tasks}
            onSelectTask={setSelectedTaskId}
          />
          <AddTaskPanel sessionId={session.session_id} />
        </section>

        <section className="fa-agent-team-panel">
          <div className="fa-agent-team-panel-header">
            <div>
              <span>{isChineseUi ? "第三步 · 分支绑定" : "Step 3 · Branch binding"}</span>
              <strong>{isChineseUi ? "Task Detail / Branch Binding" : "Task Detail / Branch Binding"}</strong>
              <HelpText>
                {isChineseUi
                  ? "点左侧任务后，确认它对应的分支线程、改动范围、验证结果和风险。"
                  : "Click a task on the left to confirm its branch thread, scope, verification, and risks."}
              </HelpText>
            </div>
          </div>
          <TaskDetail artifacts={view.artifacts ?? []} task={selectedTask} />
        </section>

        <section className="fa-agent-team-panel">
          <div className="fa-agent-team-panel-header">
            <div>
              <span>{isChineseUi ? "第四步 · 产出与风险" : "Step 4 · Outputs and risks"}</span>
              <strong>{isChineseUi ? "Outputs / Status" : "Outputs / Status"}</strong>
              <HelpText>
                {isChineseUi
                  ? "这里聚合跨任务文件、artifact 和阻塞项，方便合并前最后检查。"
                  : "This aggregates cross-task files, artifacts, and blockers before merge review."}
              </HelpText>
            </div>
          </div>
          <div className="fa-agent-team-detail">
            <section>
              <h3>{isChineseUi ? "Changed files" : "Changed files"}</h3>
              <FieldList items={changedFiles} />
            </section>
            <section>
              <h3>{isChineseUi ? "Artifact IDs" : "Artifact IDs"}</h3>
              <FieldList items={outputArtifactIds} />
            </section>
            <section>
              <h3>{isChineseUi ? "Blocked / Risks" : "Blocked / Risks"}</h3>
              <FieldList items={tasks.flatMap((task) => task.risk_notes ?? [])} />
            </section>
          </div>
        </section>
      </div>

      <MergeBundleCard
        bundle={view.merge_bundle ?? null}
        error={mergeProposal.error}
        isGenerating={mergeProposal.isPending}
        pendingBundle={pendingBundle}
        canGenerate={tasks.length > 0}
        onGenerate={() => mergeProposal.mutate()}
      />
    </div>
  );
}
