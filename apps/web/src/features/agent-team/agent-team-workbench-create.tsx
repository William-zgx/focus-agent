import { Link } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useConversations } from "@/features/conversations/use-conversations";
import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import { tooltipProps } from "@/shared/ui/tooltip";

import {
  errorMessage,
  statusLabel,
  titleFromGoal,
} from "./agent-team-workbench-utils";
import { EmptyList, HelpText, WorkflowGuide } from "./agent-team-workbench-shared";
import { useAgentTeamSessions, useCreateAgentTeamSession } from "./use-agent-team";
import type { AgentTeamActionResponse, AgentTeamClientContract } from "./types";

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
          <span>{isChineseUi ? "最近" : "Recent"}</span>
          <strong>{isChineseUi ? "最近 Mission" : "Recent missions"}</strong>
        </div>
      </div>
      {recentSessions.isLoading ? (
        <EmptyList>{isChineseUi ? "正在加载最近 Mission..." : "Loading recent missions..."}</EmptyList>
      ) : recentSessions.error ? (
        <div className="fa-inline-notice is-danger">
          {errorMessage(recentSessions.error, isChineseUi ? "最近 Mission 加载失败。" : "Failed to load recent missions.")}
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
              ? "当前来源对话还没有 Mission。"
              : "No mission exists for this source conversation yet."
            : isChineseUi
              ? "还没有 Mission。创建后会出现在这里。"
              : "No mission yet. New missions will appear here."}
        </EmptyList>
      )}
    </section>
  );
}

export function CreateSessionPanel() {
  const { isChineseUi } = useShellUi();
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const conversationsQuery = useConversations();
  const createSession = useCreateAgentTeamSession();
  const [goal, setGoal] = useState("");
  const [planError, setPlanError] = useState<Error | null>(null);
  const [isPlanningNewSession, setIsPlanningNewSession] = useState(false);
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
    if (!nextGoal || !nextRootThreadId || createSession.isPending || isPlanningNewSession) return;
    setPlanError(null);
    setIsPlanningNewSession(true);
    try {
      const response = await createSession.mutateAsync({
        goal: nextGoal,
        title: titleFromGoal(nextGoal),
        root_thread_id: nextRootThreadId,
      });
      const session = "session" in response ? response.session : response;
      const agentTeam = client as Partial<AgentTeamClientContract>;
      let plannedResponse: AgentTeamActionResponse | null = null;
      try {
        if (agentTeam.planAgentTeamSession) {
          plannedResponse = await agentTeam.planAgentTeamSession(session.session_id, { create_branches: true });
        } else if (agentTeam.dispatchAgentTeamSession) {
          plannedResponse = await agentTeam.dispatchAgentTeamSession(session.session_id, { create_branches: true });
        }
        if (plannedResponse) {
          queryClient.setQueryData(queryKeys.agentTeamSession(session.session_id), plannedResponse);
        }
      } catch (error) {
        setPlanError(error instanceof Error ? error : new Error(String(error)));
        void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(session.session_id) });
      }
      window.history.pushState(null, "", `/app/agent-team/${encodeURIComponent(session.session_id)}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } finally {
      setIsPlanningNewSession(false);
    }
  }
  const createHelp = isChineseUi
    ? "选择来源对话，写下 Mission 目标，系统会创建 Mission 并生成协作方案。"
    : "Choose the source conversation and write the mission goal; the system creates the mission and generates the collaboration plan.";

  return (
    <div className="fa-agent-team-layout fa-agent-team-workspace-shell is-create">
      <section className="fa-header-card fa-agent-team-compact-header">
        <div className="fa-chat-header-top">
          <div className="fa-chat-header-copy">
            <div className="fa-agent-team-title-block">
              <span className="fa-observability-kicker">
                {isChineseUi ? "Agent Team · Mission Runner" : "Agent Team · Mission Runner"}
              </span>
              <h1>{isChineseUi ? "创建 Mission" : "Create mission"}</h1>
              <p {...tooltipProps(createHelp)}>
                {isChineseUi
                  ? "从来源对话抽取上下文，生成可运行的任务 DAG。"
                  : "Use source conversation context to generate a runnable task DAG."}
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
              <span>{isChineseUi ? "来源对话 + Mission 目标" : "Source conversation + mission goal"}</span>
              <strong>{isChineseUi ? "创建任务计划入口" : "Create the task plan entrypoint"}</strong>
              <HelpText>
                {isChineseUi
                  ? "默认会优先选中最近对话；提交后会自动进入已拆解的 Mission。"
                  : "The newest conversation is selected by default. Submitting opens the mission after planning."}
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
            <span>{isChineseUi ? "Mission 目标" : "Mission goal"}</span>
            <textarea
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder={
                isChineseUi
                  ? "例如：把 Agent Team Web 从任务看板改成 Mission Runner，并补齐验证依据。"
                  : "Example: Turn Agent Team Web from a task board into a Mission Runner and capture verification evidence."
              }
            />
            <HelpText>
              {isChineseUi
                ? "写清楚这次 Mission 的结果、边界和验收信号；标题会自动取目标摘要。"
                : "Describe the mission outcome, boundary, and acceptance signal; the title is generated from the goal."}
            </HelpText>
          </label>
          {createSession.error ? (
            <div className="fa-inline-notice is-danger">
              {errorMessage(createSession.error, isChineseUi ? "创建失败。" : "Failed to create session.")}
            </div>
          ) : null}
          {planError ? (
            <div className="fa-inline-notice is-warning">
              {errorMessage(
                planError,
                isChineseUi
                  ? "Mission 已创建，但自动生成方案失败。进入后可以手动重试。"
                  : "The mission was created, but automatic planning failed. You can retry after entering it.",
              )}
            </div>
          ) : null}
          <div className="fa-agent-team-submit-row">
            <button
              className="fa-observability-preset is-primary"
              disabled={!goal.trim() || !rootThreadId.trim() || createSession.isPending || isPlanningNewSession}
              type="submit"
            >
              {createSession.isPending || isPlanningNewSession
                ? isChineseUi
                  ? "生成方案中..."
                  : "Generating plan..."
                : isChineseUi
                  ? "生成协作方案"
                  : "Generate collaboration plan"}
            </button>
            {!goal.trim() || !rootThreadId.trim() ? (
              <HelpText>
                {isChineseUi
                  ? "选择来源对话并填写 Mission 目标后即可创建。"
                  : "Choose a source conversation and fill the mission goal to create it."}
              </HelpText>
            ) : null}
          </div>
        </form>

        <div className="fa-agent-team-create-side">
          <RecentSessionsPanel rootThreadId={rootThreadId} />
        </div>
      </div>
    </div>
  );
}
