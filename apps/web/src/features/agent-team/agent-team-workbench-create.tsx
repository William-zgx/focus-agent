import { Link } from "@tanstack/react-router";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useConversations } from "@/features/conversations/use-conversations";
import { tooltipProps } from "@/shared/ui/tooltip";

import {
  DEFAULT_TASK_ROLES,
  errorMessage,
  roleHint,
  roleLabel,
  statusLabel,
  titleFromGoal,
} from "./agent-team-workbench-utils";
import { EmptyList, HelpText, WorkflowGuide } from "./agent-team-workbench-shared";
import { useAgentTeamSessions, useCreateAgentTeamSession } from "./use-agent-team";

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

export function CreateSessionPanel() {
  const { isChineseUi } = useShellUi();
  const conversationsQuery = useConversations();
  const createSession = useCreateAgentTeamSession();
  const [goal, setGoal] = useState("");
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
      title: titleFromGoal(nextGoal),
      root_thread_id: nextRootThreadId,
    });
    const session = "session" in response ? response.session : response;
    window.history.pushState(null, "", `/app/agent-team/${encodeURIComponent(session.session_id)}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
  const createHelp = isChineseUi
    ? "选择来源对话，写下协作目标，然后创建一个可以派生多个 Agent 分支的协作空间。"
    : "Choose the source conversation, write the collaboration goal, and create a workspace that can fork agent branches.";

  return (
    <div className="fa-agent-team-layout fa-agent-team-workspace-shell is-create">
      <section className="fa-header-card fa-agent-team-compact-header">
        <div className="fa-chat-header-top">
          <div className="fa-chat-header-copy">
            <div className="fa-agent-team-title-block">
              <span className="fa-observability-kicker">
                {isChineseUi ? "Agent Team · 并发开发控制台" : "Agent Team · Concurrent development"}
              </span>
              <h1>{isChineseUi ? "创建并发开发工作台" : "Create a concurrent development workspace"}</h1>
              <p {...tooltipProps(createHelp)}>
                {isChineseUi
                  ? "从来源对话派生多个 Agent 分支，并行推进开发任务。"
                  : "Fork source-conversation context into agent lanes that work in parallel."}
              </p>
            </div>
          </div>
        </div>
      </section>

      <WorkflowGuide compact />

      <div className="fa-agent-team-create-grid fa-agent-team-stage">
        <form className="fa-agent-team-panel fa-agent-team-create-form" onSubmit={handleSubmit}>
          <div className="fa-agent-team-panel-header">
            <div>
              <span>{isChineseUi ? "第一步" : "Step 1"}</span>
              <strong>{isChineseUi ? "选择对话并写目标" : "Choose conversation and goal"}</strong>
              <HelpText>
                {isChineseUi
                  ? "默认会优先选中最近的对话；只有调试或外部线程才需要手动输入 ID。"
                  : "The newest conversation is selected by default. Manual IDs are only for debugging or external threads."}
              </HelpText>
            </div>
          </div>
          <label className="fa-agent-team-field">
            <span>{isChineseUi ? "来源对话" : "Source conversation"}</span>
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
                ? "写清楚这组 Agent 要一起完成什么；标题会自动取目标摘要。"
                : "Describe what the agent team should accomplish; the title is generated from the goal."}
            </HelpText>
          </label>
          {createSession.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(createSession.error, isChineseUi ? "创建失败。" : "Failed to create session.")}
            </div>
          ) : null}
          <div className="fa-agent-team-submit-row">
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
                  ? "选择来源对话并填写协作目标后即可创建。"
                  : "Choose a source conversation and fill the team goal to create the workspace."}
              </HelpText>
            ) : null}
          </div>
        </form>

        <div className="fa-agent-team-create-side">
          <section className="fa-agent-team-panel fa-agent-team-roles-panel">
            <div className="fa-agent-team-panel-header">
              <div>
                <span>{isChineseUi ? "默认分工" : "Default lanes"}</span>
                <strong>{isChineseUi ? "创建后可一键生成 6 个 Agent 任务" : "Create six agent tasks after setup"}</strong>
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
          <RecentSessionsPanel rootThreadId={rootThreadId} />
        </div>
      </div>
    </div>
  );
}
