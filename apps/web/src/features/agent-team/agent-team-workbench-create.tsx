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

type MissionCollaborationMode = {
  id: string;
  title: string;
  titleEn: string;
  description: string;
  descriptionEn: string;
  granularity: "coarse" | "balanced" | "detailed";
  focus: "implementation" | "verification" | "auto";
  maxTasks: number;
};

const MISSION_PRESETS: MissionPreset[] = [
  {
    id: "ship",
    title: "做功能",
    titleEn: "Build feature",
    description: "描述目标，自动拆成交付 DAG。",
    descriptionEn: "Describe the goal; Agent Team compiles the delivery DAG.",
    goal: "想达成什么：\n最终需要什么结果：\n已有上下文、约束或风险：",
    goalEn: "What to achieve:\nFinal result needed:\nKnown context, constraints, or risks:",
  },
  {
    id: "diagnose",
    title: "查问题",
    titleEn: "Find issue",
    description: "说明现象，自动安排定位与验证。",
    descriptionEn: "Describe the symptom; Agent Team plans investigation and verification.",
    goal: "现象：\n已知线索：\n希望得到的结论：",
    goalEn: "Symptom:\nKnown clues:\nDecision needed:",
  },
  {
    id: "review",
    title: "看改动",
    titleEn: "Review changes",
    description: "给出对象，自动拆风险和证据检查。",
    descriptionEn: "Provide the target; Agent Team splits risk and evidence checks.",
    goal: "审查对象：\n重点风险：\n希望输出：",
    goalEn: "Review target:\nKey risks:\nExpected output:",
  },
  {
    id: "research",
    title: "做调研",
    titleEn: "Research",
    description: "提出问题，自动拆比较与建议。",
    descriptionEn: "Ask the question; Agent Team splits comparison and recommendation work.",
    goal: "要决策的问题：\n约束条件：\n需要比较或验证的方向：",
    goalEn: "Decision to make:\nConstraints:\nOptions or assumptions to compare:",
  },
];

const COLLABORATION_MODES: MissionCollaborationMode[] = [
  {
    id: "fast",
    title: "快一点",
    titleEn: "Fast",
    description: "少拆任务，尽快给结果。",
    descriptionEn: "Fewer agents, optimized for implementation and quick closure.",
    granularity: "coarse",
    focus: "implementation",
    maxTasks: 4,
  },
  {
    id: "balanced",
    title: "稳一点",
    titleEn: "Balanced",
    description: "兼顾执行和检查。",
    descriptionEn: "Balanced implementation and verification for most changes.",
    granularity: "balanced",
    focus: "verification",
    maxTasks: 6,
  },
  {
    id: "detailed",
    title: "细一点",
    titleEn: "Detailed",
    description: "拆得更细，检查更多。",
    descriptionEn: "More agents with finer-grained split and acceptance.",
    granularity: "detailed",
    focus: "auto",
    maxTasks: 8,
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
  const [selectedCollaborationId, setSelectedCollaborationId] = useState(COLLABORATION_MODES[1]?.id ?? "");
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
  const selectedCollaboration =
    COLLABORATION_MODES.find((mode) => mode.id === selectedCollaborationId) ?? COLLABORATION_MODES[1];
  const missingInputs = [
    !goal.trim() ? (isChineseUi ? "填写 Mission 目标" : "Fill the mission goal") : null,
  ].filter(Boolean);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextGoal = goal.trim();
    const nextRootThreadId = rootThreadId.trim();
    if (!nextGoal || createSession.isPending || isPlanningNewSession) return;
    setPlanError(null);
    setIsPlanningNewSession(true);
    try {
      const sessionPayload = {
        goal: nextGoal,
        title: titleFromGoal(nextGoal),
        ...(nextRootThreadId ? { root_thread_id: nextRootThreadId } : {}),
      };
      const response = await createSession.mutateAsync(sessionPayload);
      const session = "session" in response ? response.session : response;
      const agentTeam = client as Partial<AgentTeamClientContract>;
      let plannedResponse: AgentTeamActionResponse | null = null;
      try {
        if (agentTeam.planAgentTeamSession) {
          plannedResponse = await agentTeam.planAgentTeamSession(session.session_id, {
            create_branches: Boolean(nextRootThreadId),
            focus: selectedCollaboration.focus,
            granularity: selectedCollaboration.granularity,
            max_tasks: selectedCollaboration.maxTasks,
          });
        } else if (agentTeam.dispatchAgentTeamSession) {
          plannedResponse = await agentTeam.dispatchAgentTeamSession(session.session_id, { create_branches: Boolean(nextRootThreadId) });
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
    ? "把一个目标交给 Agent Team，系统会按交付物自动拆解依赖任务并生成可运行 DAG。"
    : "Give Agent Team a goal; it will decompose deliverables into a runnable dependency DAG.";

  return (
    <div className="fa-agent-team-layout fa-agent-team-workspace-shell fa-agent-team-studio is-create">
      <section className="fa-agent-team-studio-header">
        <div>
          <span className="fa-observability-kicker">Mission DAG</span>
          <h1>{isChineseUi ? "把目标拆成可运行的 Agent DAG" : "Turn a goal into a runnable Agent DAG"}</h1>
          <p {...tooltipProps(createHelp)}>
            {isChineseUi
              ? "填写目标和可选上下文；Agent Team 自动规划任务、依赖、执行与结果汇总。"
              : "Set a goal and optional context; Agent Team plans tasks, dependencies, execution, and result synthesis."}
          </p>
        </div>
        <svg className="fa-agent-team-studio-dag" viewBox="0 0 236 82" aria-hidden="true">
          <defs>
            <linearGradient id="agent-team-dag-edge" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor="currentColor" stopOpacity="0.18" />
              <stop offset="0.55" stopColor="currentColor" stopOpacity="0.72" />
              <stop offset="1" stopColor="currentColor" stopOpacity="0.28" />
            </linearGradient>
          </defs>
          <path className="edge" d="M45 41 C64 18 75 18 94 22" />
          <path className="edge" d="M45 41 C64 64 75 64 94 60" />
          <path className="edge" d="M122 22 C137 18 145 22 158 31" />
          <path className="edge" d="M122 60 C137 64 145 60 158 51" />
          <path className="edge edge-strong" d="M184 41 C197 41 204 41 216 41" />
          <g className="node node-root" transform="translate(12 29)">
            <rect width="38" height="24" rx="12" />
            <text x="19" y="16">Goal</text>
          </g>
          <g className="node" transform="translate(88 10)">
            <rect width="42" height="24" rx="12" />
            <text x="21" y="16">Plan</text>
          </g>
          <g className="node" transform="translate(88 48)">
            <rect width="42" height="24" rx="12" />
            <text x="21" y="16">Build</text>
          </g>
          <g className="node" transform="translate(150 10)">
            <rect width="48" height="24" rx="12" />
            <text x="24" y="16">Check</text>
          </g>
          <g className="node" transform="translate(150 48)">
            <rect width="48" height="24" rx="12" />
            <text x="24" y="16">Merge</text>
          </g>
          <g className="node node-final" transform="translate(184 29)">
            <rect width="44" height="24" rx="12" />
            <text x="22" y="16">Result</text>
          </g>
        </svg>
      </section>

      <div className="fa-agent-team-studio-grid fa-agent-team-stage">
        <form className="fa-agent-team-panel fa-agent-team-create-form fa-agent-team-studio-form" onSubmit={handleSubmit}>
          <div className="fa-agent-team-studio-section">
            <div className="fa-agent-team-studio-section-heading">
              <span>{isChineseUi ? "目标" : "Goal"}</span>
              <strong>{isChineseUi ? "选择 Mission 类型" : "Choose mission type"}</strong>
              <HelpText>
                {isChineseUi
                  ? "这些只是输入提示；最终会按目标所需交付物自动生成任务 DAG。"
                  : "These are input hints; the final task DAG is generated from required deliverables."}
              </HelpText>
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
              <span>{isChineseUi ? "协作偏好" : "Collaboration"}</span>
              <strong>{isChineseUi ? "选择协作模式" : "Choose collaboration mode"}</strong>
              <HelpText>
                {isChineseUi
                  ? "偏好只限制粒度和侧重点；真正的任务图会从目标所需交付物反推。"
                  : "Preferences only bound granularity and focus; the task graph is compiled from required deliverables."}
              </HelpText>
            </div>
            <div className="fa-agent-team-collab-grid" role="list">
              {COLLABORATION_MODES.map((mode) => {
                const isSelected = mode.id === selectedCollaborationId;
                return (
                  <button
                    aria-pressed={isSelected}
                    className={`fa-agent-team-collab-card ${isSelected ? "is-selected" : ""}`.trim()}
                    key={mode.id}
                    onClick={() => setSelectedCollaborationId(mode.id)}
                    type="button"
                  >
                    <strong>{isChineseUi ? mode.title : mode.titleEn}</strong>
                    <span>{isChineseUi ? mode.description : mode.descriptionEn}</span>
                    <small>{mode.granularity} · {mode.focus} · {mode.maxTasks} tasks</small>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="fa-agent-team-studio-section">
            <div className="fa-agent-team-studio-section-heading">
              <span>{isChineseUi ? "上下文" : "Context"}</span>
              <strong>{isChineseUi ? "上下文与目标" : "Context and goal"}</strong>
              <HelpText>
                {isChineseUi
                  ? "写清楚想达成的结果即可；Agent Team 会自动推导交付物、任务依赖和验收证据。"
                  : "Describe the result you need; Agent Team will infer deliverables, dependencies, and evidence gates."}
              </HelpText>
            </div>
            <label className="fa-agent-team-field">
              <span>{isChineseUi ? "来源对话（可选）" : "Source conversation (optional)"}</span>
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
                      ? "不绑定来源，直接创建独立 Mission"
                      : "No source; create standalone mission"}
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
              disabled={!goal.trim() || createSession.isPending || isPlanningNewSession}
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
            {!goal.trim() ? (
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
