import { useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";

import { AgentTeamSessionState } from "./agent-team-session-state";
import {
	TaskDetailPanel,
	TaskLanesPanel,
} from "./agent-team-workbench-task-lanes";
import { normalizeSessionView } from "./agent-team-workbench-utils";
import { useAgentTeamSession, usePlanAgentTeamSession } from "./use-agent-team";

export function AgentTeamTasksTab({ sessionId }: { sessionId: string | null }) {
	const { isChineseUi } = useShellUi();
	const sessionQuery = useAgentTeamSession(sessionId);
	const planSession = usePlanAgentTeamSession(sessionId);
	const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
	const state = (
		<AgentTeamSessionState
			data={sessionQuery.data}
			error={sessionQuery.error}
			isChineseUi={isChineseUi}
			isLoading={sessionQuery.isLoading}
		/>
	);
	const view = normalizeSessionView(sessionQuery.data);

	if (!sessionId || sessionQuery.isLoading || sessionQuery.error || !view) {
		return state;
	}

	const selectedTask =
		view.tasks.find((task) => task.task_id === selectedTaskId) ??
		view.tasks[0] ??
		null;

	return (
		<div className="fa-agent-team-layout fa-agent-team-tab-content">
			<TaskLanesPanel
				artifacts={view.artifacts}
				dispatchError={planSession.error}
				dispatchPending={planSession.isPending}
				onGeneratePlan={() =>
					planSession.mutate({ create_branches: true, replace_existing: true })
				}
				onSelectTask={setSelectedTaskId}
				outputs={view.outputs}
				rootThreadId={view.session.root_thread_id}
				selectedTaskId={selectedTask?.task_id ?? null}
				taskCount={view.tasks.length}
				tasks={view.tasks}
			/>
			<TaskDetailPanel
				artifacts={view.artifacts ?? []}
				outputs={view.outputs ?? []}
				selectedTask={selectedTask}
				tasks={view.tasks}
			/>
		</div>
	);
}
