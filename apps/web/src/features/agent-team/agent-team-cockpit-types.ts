import type { useAgentTeamWorkbenchViewModel } from "./agent-team-workbench-view-model";
import type { AgentTeamSessionView } from "./types";

export type AgentTeamCockpitViewModel = ReturnType<
	typeof useAgentTeamWorkbenchViewModel
> & {
	primaryAction: ReturnType<
		typeof useAgentTeamWorkbenchViewModel
	>["primaryAction"] & {
		busy?: boolean;
		label: string;
	};
};

export type AgentTeamCockpitTaskDisplayState =
	AgentTeamCockpitViewModel["taskDisplayStates"][number];

export interface AgentTeamCockpitActions {
	confirmResultPending: boolean;
	onConfirmResult: () => void;
	onGeneratePlan: () => void;
	onGenerateResult: () => void;
	onPrimaryAction: () => void;
	onRunReadyTasks: (taskIds?: string[]) => void;
	onSelectTask: (taskId: string) => void;
}

export interface AgentTeamCockpitInspector {
	isOpen: boolean;
	onToggle: () => void;
}

export interface AgentTeamCockpitProps {
	actions: AgentTeamCockpitActions;
	inspector: AgentTeamCockpitInspector;
	session: AgentTeamSessionView;
	viewModel: AgentTeamCockpitViewModel;
}
