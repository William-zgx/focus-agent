import { Link } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useMemo, useState } from "react";

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

type MissionPreset = {
  id: string;
  title: string;
  titleEn: string;
  description: string;
  descriptionEn: string;
  goal: string;
  goalEn: string;
};

const MISSION_PRESETS: MissionPreset[] = [
  {
    id: "ship",
    title: "做完一个功能",
    titleEn: "Ship a feature",
    description: "拆实现、验证、审查，适合代码改动。",
    descriptionEn: "Implementation, verification, and review for code changes.",
    goal: "实现：\n验收标准：\n不做范围：",
    goalEn: "Implement:\nAcceptance criteria:\nOut of scope:",
  },
  {
    id: "diagnose",
    title: "定位一个问题",
    titleEn: "Diagnose an issue",
    description: "先找证据，再给修复路径，适合 bug 或线上风险。",
    descriptionEn: "Gather evidence first, then propose a fix path.",
    goal: "现象：\n影响：\n希望定位到：",
    goalEn: "Symptom:\nImpact:\nNeed to identify:",
  },
  {
    id: "review",
    title: "审查一批改动",
    titleEn: "Review changes",
    description: "并行看正确性、风险和测试缺口。",
    descriptionEn: "Review correctness, risk, and test gaps in parallel.",
    goal: "审查对象：\n重点关注：\n输出格式：",
    goalEn: "Review target:\nFocus areas:\nOutput format:",
  },
  {
    id: "research",
    title: "调研并给方案",
    titleEn: "Research a plan",
    description: "拆调研、比较、建议，适合技术选型。",
    descriptionEn: "Split research, comparison, and recommendation work.",
    goal: "要决策的问题：\n约束：\n需要比较的选项：",
    goalEn: "Decision to make:\nConstraints:\nOptions to compare:",
  },
];

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
  const defaultPreset = MISSION_PRESETS[0];
  const [goal, setGoal] = useState(() => (isChineseUi ? defaultPreset?.goal : defaultPreset?.goalEn) ?? "");
  const [selectedPresetId, setSelectedPresetId] = useState(MISSION_PRESETS[0]?.id ?? "");
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
  const selectedPreset = MISSION_PRESETS.find((preset) => preset.id === selectedPresetId) ?? MISSION_PRESETS[0];
  const missingInputs = [
    !rootThreadId.trim() ? (isChineseUi ? "选择来源对话" : "Choose a source conversation") : null,
    !goal.trim() ? (isChineseUi ? "填写 Mission 目标" : "Fill the mission goal") : null,
  ].filter(Boolean);

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
    ? "选择一个任务类型，填好目标，进入 Mission 后只需要按主按钮推进。"
    : "Pick a mission type, fill the goal, then use the primary button to move forward.";

  return (
    <div className="fa-agent-team-layout fa-agent-team-workspace-shell fa-agent-team-studio is-create">
      <section className="fa-agent-team-studio-header">
        <div>
          <span className="fa-observability-kicker">Agent Team</span>
          <h1>{isChineseUi ? "开一个 Mission" : "Start a mission"}</h1>
          <p {...tooltipProps(createHelp)}>
            {isChineseUi
              ? "把一句目标变成一组 Agent 分工；页面会告诉你下一步该点哪里。"
              : "Turn one goal into agent work; the page keeps the next action obvious."}
          </p>
        </div>
        <div className="fa-agent-team-studio-meter" aria-hidden="true">
          <span>1</span>
          <i />
          <span>2</span>
          <i />
          <span>3</span>
        </div>
      </section>

      <div className="fa-agent-team-studio-grid fa-agent-team-stage">
        <form className="fa-agent-team-panel fa-agent-team-create-form fa-agent-team-studio-form" onSubmit={handleSubmit}>
          <div className="fa-agent-team-studio-section">
            <div className="fa-agent-team-studio-section-heading">
              <span>{isChineseUi ? "第一步" : "Step 1"}</span>
              <strong>{isChineseUi ? "这次要让 Agent Team 做什么？" : "What should Agent Team do?"}</strong>
            </div>
            <div className="fa-agent-team-preset-grid" role="list">
              {MISSION_PRESETS.map((preset) => {
                const isSelected = preset.id === selectedPresetId;
                return (
                  <button
                    aria-pressed={isSelected}
                    className={`fa-agent-team-preset ${isSelected ? "is-selected" : ""}`.trim()}
                    key={preset.id}
                    onClick={() => {
                      setSelectedPresetId(preset.id);
                      if (!goal.trim()) {
                        setGoal(isChineseUi ? preset.goal : preset.goalEn);
                      }
                    }}
                    type="button"
                  >
                    <strong>{isChineseUi ? preset.title : preset.titleEn}</strong>
                    <span>{isChineseUi ? preset.description : preset.descriptionEn}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="fa-agent-team-studio-section">
            <div className="fa-agent-team-studio-section-heading">
              <span>{isChineseUi ? "第二步" : "Step 2"}</span>
              <strong>{isChineseUi ? "绑定来源和目标" : "Bind source and goal"}</strong>
              <HelpText>
                {isChineseUi
                  ? "来源对话提供上下文；目标决定拆成哪些 Agent 任务。"
                  : "The source gives context; the goal decides the agent task split."}
              </HelpText>
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
                placeholder={isChineseUi ? selectedPreset.goal : selectedPreset.goalEn}
              />
            </label>
          </div>

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
              className="fa-agent-team-button is-primary"
              disabled={!goal.trim() || !rootThreadId.trim() || createSession.isPending || isPlanningNewSession}
              type="submit"
            >
              {createSession.isPending || isPlanningNewSession
                ? isChineseUi
                  ? "生成方案中..."
                  : "Starting mission..."
                : isChineseUi
                  ? "开 Mission 并生成协作方案"
                  : "Start mission and plan"}
            </button>
            {!goal.trim() || !rootThreadId.trim() ? (
              <HelpText>
                {isChineseUi
                  ? `还需要：${missingInputs.join("、")}。`
                  : `Still needed: ${missingInputs.join(", ")}.`}
              </HelpText>
            ) : null}
          </div>
        </form>

        <div className="fa-agent-team-create-side">
          <WorkflowGuide compact />
          <RecentSessionsPanel rootThreadId={rootThreadId} />
        </div>
      </div>
    </div>
  );
}
