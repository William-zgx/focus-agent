import { Link } from "@tanstack/react-router";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { CreateSessionPanel } from "./agent-team-workbench-create";
import { MergeBundleCard, PreMergeCheckPanel, riskItemsFromTasks } from "./agent-team-workbench-merge-handoff";
import { StatusLegend, StatusPill, WorkflowGuide } from "./agent-team-workbench-shared";
import { TaskDetailPanel, TaskLanesPanel } from "./agent-team-workbench-task-lanes";
import { useAgentTeamWorkbenchViewModel } from "./agent-team-workbench-view-model";
import { defaultTaskActionLabel, errorMessage, mergeBundleActionLabel } from "./agent-team-workbench-utils";
import {
  useAgentTeamMergeProposal,
  useAgentTeamSession,
  useDispatchAgentTeamSession,
} from "./use-agent-team";

export function AgentTeamWorkbench({ sessionId }: { sessionId: string | null }) {
  const { isChineseUi } = useShellUi();
  const sessionQuery = useAgentTeamSession(sessionId);
  const dispatchSession = useDispatchAgentTeamSession(sessionId);
  const mergeProposal = useAgentTeamMergeProposal(sessionId);
  const {
    activeBundle,
    changedFiles,
    defaultTasksReady,
    displayTitle,
    evidenceItems,
    nextStep,
    pendingBundle,
    selectedTask,
    setSelectedTaskId,
    tasks,
    view,
  } = useAgentTeamWorkbenchViewModel({
    isChineseUi,
    mergeProposalData: mergeProposal.data,
    sessionData: sessionQuery.data,
  });

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
  const sessionHeaderHelp = isChineseUi
    ? "这是从来源对话派生出的并发开发控制台：生成任务、进入分支执行、汇总证据并准备合并。"
    : "This concurrent development console is derived from the source conversation: create tasks, work in branches, collect evidence, and prepare merge.";

  return (
    <div className="fa-agent-team-layout fa-agent-team-workspace-shell">
      <section className="fa-header-card fa-agent-team-compact-header">
        <div className="fa-chat-header-top">
          <div className="fa-chat-header-copy">
            <div className="fa-agent-team-title-block">
              <span className="fa-observability-kicker">
                {isChineseUi ? "Agent Team · 并发开发控制台" : "Agent Team · Concurrent development"}
              </span>
              <h1 {...tooltipProps(session.goal)}>
                {isChineseUi
                  ? `并发开发工作台：${displayTitle || session.session_id}`
                  : `Concurrent development: ${displayTitle || session.session_id}`}
              </h1>
              <p {...tooltipProps(sessionHeaderHelp)}>{nextStep.label}</p>
            </div>
          </div>
          <div className="fa-chat-header-right-actions fa-agent-team-header-actions">
            <StatusPill status={session.status} />
            <Link
              className="fa-chat-toolbar-button"
              params={{ conversationId: session.root_thread_id, threadId: session.root_thread_id }}
              to="/c/$conversationId/t/$threadId"
              {...tooltipProps(isChineseUi ? "返回来源对话" : "Back to source conversation")}
            >
              {isChineseUi ? "返回对话" : "Source"}
            </Link>
            <button
              className="fa-chat-toolbar-button"
              disabled={defaultTasksReady || dispatchSession.isPending}
              onClick={() => dispatchSession.mutate({ create_branches: true })}
              type="button"
              {...tooltipProps(
                isChineseUi
                  ? "生成或补齐规划、执行、测试、审查、验证任务"
                  : "Create or fill planning, execution, test, review, and verification tasks",
              )}
            >
              {defaultTaskActionLabel({
                isChineseUi,
                isPending: dispatchSession.isPending,
                defaultTasksReady,
                taskCount: tasks.length,
              })}
            </button>
            <button
              className="fa-chat-toolbar-button is-primary"
              disabled={!tasks.length || mergeProposal.isPending}
              onClick={() => mergeProposal.mutate()}
              type="button"
              {...tooltipProps(
                isChineseUi ? "汇总改动、证据、风险和未决问题" : "Summarize changes, evidence, risks, and open questions",
              )}
            >
              {mergeBundleActionLabel({
                isChineseUi,
                isGenerating: mergeProposal.isPending,
                canGenerate: tasks.length > 0,
                hasBundle: Boolean(activeBundle),
              })}
            </button>
          </div>
        </div>
      </section>

      <WorkflowGuide compact />

      <div className="fa-agent-team-next-step">
        <span>{isChineseUi ? "下一步" : "Next"}</span>
        <strong {...tooltipProps(nextStep.help)}>{nextStep.label}</strong>
        <div className="fa-agent-team-progress-strip">
          <span {...tooltipProps(isChineseUi ? "Agent 任务数量" : "Agent task count")}>
            {isChineseUi ? "任务" : "Tasks"} · {tasks.length}
          </span>
          <span
            {...tooltipProps(
              isChineseUi
                ? "包含 artifact、任务验证摘要和协作汇总里的测试证据"
                : "Includes artifacts, task verification summaries, and merge-bundle test evidence",
            )}
          >
            {isChineseUi ? "证据" : "Evidence"} · {evidenceItems.length}
          </span>
          <span {...tooltipProps(isChineseUi ? "跨任务汇总出的改动文件数量" : "Changed files across tasks")}>
            {isChineseUi ? "文件" : "Files"} · {changedFiles.length}
          </span>
          <StatusLegend />
        </div>
      </div>

      <div className="fa-agent-team-workbench-grid fa-agent-team-stage">
        <TaskLanesPanel
          defaultTasksReady={defaultTasksReady}
          dispatchError={dispatchSession.error}
          dispatchPending={dispatchSession.isPending}
          onCreateDefaultTasks={() => dispatchSession.mutate({ create_branches: true })}
          onSelectTask={setSelectedTaskId}
          rootThreadId={session.root_thread_id}
          selectedTaskId={selectedTask?.task_id ?? null}
          sessionId={session.session_id}
          taskCount={tasks.length}
          tasks={tasks}
        />

        <TaskDetailPanel artifacts={view.artifacts ?? []} selectedTask={selectedTask} />

        <PreMergeCheckPanel
          changedFiles={changedFiles}
          evidenceItems={evidenceItems}
          riskItems={riskItemsFromTasks(tasks)}
        />
      </div>

      <MergeBundleCard
        bundle={activeBundle}
        error={mergeProposal.error}
        isGenerating={mergeProposal.isPending}
        pendingBundle={pendingBundle}
        canGenerate={tasks.length > 0}
        onGenerate={() => mergeProposal.mutate()}
        hideAction
      />
    </div>
  );
}
