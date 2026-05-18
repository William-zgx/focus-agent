import {
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	type SetStateAction,
} from "react";

import {
	deriveTaskDisplayStates,
	isFallbackPlan,
	isTaskDone,
	isTaskQueued,
	isTaskReady,
	isTaskRunning,
	normalizeMergeBundle,
	normalizeSessionView,
	planningSourceLabel,
	titleFromGoal,
	uniqueNonEmptyStrings,
	type AgentTeamTaskDisplayState,
} from "./agent-team-workbench-utils";
import {
	blockedExplanationForWorkbench,
	decisionDockStateForWorkbench,
	isActionableTaskState,
	isPlanReviewState,
	missionStageForWorkbench,
	nextStepForWorkbench,
	primaryActionForWorkbench,
} from "./agent-team-workbench-decision-state";
import {
	deriveWorkbenchEvidenceRiskState,
	finalPreviewStateForWorkbench,
	missionHeaderStateForWorkbench,
	missionProgressStateForWorkbench,
	userFacingResultForWorkbench,
} from "./agent-team-workbench-derived-state";
import {
	recommendedTaskReasonForSelection,
	recommendedTaskStateForSelection,
	shouldAutoAdvanceFocus,
} from "./agent-team-workbench-focus-state";
import {
	buildPhaseGroups,
	buildPhaseMapItems,
} from "./agent-team-workbench-phase-state";
import type {
	AgentTeamMergeBundle,
	AgentTeamSession,
	AgentTeamSessionView,
} from "./types";

export type {
	AgentTeamWorkbenchFinalPreviewState,
	AgentTeamWorkbenchFinalResultState,
	AgentTeamWorkbenchFinalResultStateKind,
	AgentTeamWorkbenchMissionHeaderState,
} from "./agent-team-workbench-derived-state";
export type { AgentTeamWorkbenchDecisionDockState } from "./agent-team-workbench-decision-state";
export type {
	AgentTeamWorkbenchPhaseGroup,
	AgentTeamWorkbenchPhaseKey,
	AgentTeamWorkbenchPhaseMapItem,
	AgentTeamWorkbenchPhaseMapStatus,
} from "./agent-team-workbench-phase-state";

export function useAgentTeamWorkbenchViewModel({
	isChineseUi,
	mergeProposalData,
	sessionData,
}: {
	isChineseUi: boolean;
	mergeProposalData: AgentTeamMergeBundle | AgentTeamSessionView | undefined;
	sessionData: AgentTeamSession | AgentTeamSessionView | undefined;
}) {
	const view = normalizeSessionView(sessionData);
	const tasks = view?.tasks ?? [];
	const [focusState, setFocusState] = useState<{
		manualFocusTaskId: string | null;
		selectedTaskId: string | null;
	}>({
		manualFocusTaskId: null,
		selectedTaskId: null,
	});
	const { manualFocusTaskId, selectedTaskId } = focusState;
	const manualFocusStateKindRef = useRef<
		AgentTeamTaskDisplayState["kind"] | null
	>(null);
	const setSelectedTaskId = useCallback(
		(nextTaskId: SetStateAction<string | null>) => {
			setFocusState((currentFocusState) => {
				const resolvedTaskId =
					typeof nextTaskId === "function"
						? nextTaskId(currentFocusState.selectedTaskId)
						: nextTaskId;
				return {
					manualFocusTaskId: resolvedTaskId,
					selectedTaskId: resolvedTaskId,
				};
			});
		},
		[],
	);
	const pendingBundle = normalizeMergeBundle(mergeProposalData);
	const activeBundle = pendingBundle ?? view?.merge_bundle ?? null;
	const { changedFiles, evidenceItems, riskItems } =
		deriveWorkbenchEvidenceRiskState({
			activeBundle,
			tasks,
			view,
		});
	const readyTasks = tasks.filter((task) => isTaskReady(task, tasks));
	const runningTasks = tasks.filter(isTaskRunning);
	const queuedTasks = tasks.filter(isTaskQueued);
	const doneTasks = tasks.filter(isTaskDone);
	const taskDisplayStates = deriveTaskDisplayStates(tasks, isChineseUi);
	const taskDisplayState = taskDisplayStates.reduce<
		Record<string, AgentTeamTaskDisplayState>
	>((states, state) => {
		states[state.taskId] = state;
		return states;
	}, {});
	const needsAttentionTaskStates = taskDisplayStates.filter(
		isActionableTaskState,
	);
	const waitingDependencyTaskStates = taskDisplayStates.filter(
		(state) => state.kind === "waiting_dependency",
	);
	const recommendedTaskState = useMemo(
		() => recommendedTaskStateForSelection(taskDisplayStates, tasks),
		[taskDisplayStates, tasks],
	);
	const recommendedTaskId = recommendedTaskState?.taskId ?? null;
	const selectedTaskState = selectedTaskId
		? (taskDisplayState[selectedTaskId] ?? null)
		: null;

	useEffect(() => {
		if (!selectedTaskId) {
			manualFocusStateKindRef.current = null;
			return;
		}
		const selectedTaskExists = tasks.some(
			(task) => task.task_id === selectedTaskId,
		);
		if (!selectedTaskExists) {
			setFocusState({
				manualFocusTaskId: null,
				selectedTaskId: recommendedTaskId,
			});
			manualFocusStateKindRef.current = null;
			return;
		}
		const isManualSelectedTask = manualFocusTaskId === selectedTaskId;
		const selectedTaskKind = selectedTaskState?.kind ?? null;
		const didManualTaskJustComplete =
			isManualSelectedTask &&
			selectedTaskKind === "completed" &&
			manualFocusStateKindRef.current !== null &&
			manualFocusStateKindRef.current !== "completed";
		if (
			didManualTaskJustComplete &&
			shouldAutoAdvanceFocus({
				recommendedTaskId,
				recommendedTaskState,
				selectedTaskId,
				selectedTaskState,
			})
		) {
			setFocusState({
				manualFocusTaskId: null,
				selectedTaskId: recommendedTaskId,
			});
			manualFocusStateKindRef.current = null;
			return;
		}
		manualFocusStateKindRef.current = isManualSelectedTask
			? selectedTaskKind
			: null;
	}, [
		manualFocusTaskId,
		recommendedTaskId,
		recommendedTaskState,
		selectedTaskId,
		selectedTaskState,
		tasks,
	]);

	const selectedTask = useMemo(() => {
		if (!tasks.length) return null;
		const explicitTask = selectedTaskId
			? tasks.find((task) => task.task_id === selectedTaskId)
			: null;
		if (explicitTask) return explicitTask;
		return tasks.find((task) => task.task_id === recommendedTaskId) ?? tasks[0];
	}, [recommendedTaskId, selectedTaskId, tasks]);
	const selectedTaskFocusState = selectedTask
		? (taskDisplayState[selectedTask.task_id] ?? null)
		: null;
	const session = view?.session ?? null;
	const displayTitle =
		session?.title && session.title !== session.goal
			? session.title
			: titleFromGoal(session?.goal ?? "");
	const fallbackPlan = isFallbackPlan(session, tasks);
	const planningMetadata = {
		generatedAt: session?.plan_generated_at ?? session?.updated_at ?? null,
		model:
			session?.planner_model_id?.trim() ||
			(isChineseUi ? "未记录" : "Not recorded"),
		source: planningSourceLabel(
			session?.planning_source ?? tasks[0]?.plan_source,
			isChineseUi,
		),
		taskCount: tasks.length,
	};
	const missionProgress = missionProgressStateForWorkbench({
		doneTasksCount: doneTasks.length,
		needsAttentionCount: needsAttentionTaskStates.length,
		queuedTasksCount: queuedTasks.length,
		readyTasksCount: readyTasks.length,
		runningTasksCount: runningTasks.length,
		taskCount: tasks.length,
		waitingDependencyCount: waitingDependencyTaskStates.length,
	});
	const allTasksComplete =
		tasks.length > 0 &&
		doneTasks.length >= tasks.length &&
		!runningTasks.length &&
		!queuedTasks.length &&
		!needsAttentionTaskStates.length;
	const canGenerateResult = Boolean(activeBundle) || allTasksComplete;
	const blockedExplanation = blockedExplanationForWorkbench({
		isChineseUi,
		taskDisplayStates,
	});
	const missionStage = missionStageForWorkbench({
		activeBundle,
		blockedExplanation,
		doneTasksCount: doneTasks.length,
		isChineseUi,
		readyTasksCount: readyTasks.length,
		queuedTasksCount: queuedTasks.length,
		runningTasksCount: runningTasks.length,
		taskDisplayStates,
		tasks,
	});
	const primaryAction = primaryActionForWorkbench({
		activeBundle,
		blockedExplanation,
		doneTasksCount: doneTasks.length,
		isChineseUi,
		readyTasksCount: readyTasks.length,
		queuedTasksCount: queuedTasks.length,
		runningTasksCount: runningTasks.length,
		taskDisplayStates,
		tasks,
	});
	const missionHeaderState = missionHeaderStateForWorkbench({
		displayTitle,
		fallbackPlan,
		isChineseUi,
		missionProgress,
		missionStage,
		planningMetadata,
		session,
	});
	const userFacingResult = userFacingResultForWorkbench({
		activeBundle,
		changedFiles,
		evidenceItems,
		isChineseUi,
		riskItems,
	});
	const advancedMeta = {
		planning: {
			...planningMetadata,
			rationale:
				session?.planning_rationale ?? view?.planning?.rationale ?? null,
			planHash: session?.plan_hash ?? view?.planning?.plan_hash ?? null,
			error: session?.planning_error ?? view?.planning?.error ?? null,
		},
		dag: view?.dag ?? null,
		rawEvidence: {
			evidenceItems,
			executionEvidence: activeBundle?.execution_evidence ?? [],
			testEvidence: activeBundle?.test_evidence ?? [],
		},
		changedFiles: uniqueNonEmptyStrings([
			...(activeBundle?.changed_files ?? []),
			...changedFiles,
		]),
		artifacts: view?.artifacts ?? [],
		openQuestions: activeBundle?.open_questions ?? [],
	};
	const nextStepHint = nextStepForWorkbench({
		activeBundle,
		blockedExplanation,
		changedFiles,
		evidenceItems,
		isChineseUi,
		readyTasksCount: readyTasks.length,
		runningTasksCount: runningTasks.length,
		taskDisplayStates,
		tasks,
	});
	const isPlanReview = isPlanReviewState({
		activeBundle,
		taskDisplayStates,
		tasks,
	});
	const phaseGroups = buildPhaseGroups(tasks, taskDisplayState, isChineseUi);
	const phaseMapItems = buildPhaseMapItems({
		isChineseUi,
		phaseGroups,
		recommendedTaskId,
		selectedTaskId: selectedTask?.task_id ?? null,
	});
	const focusReason = recommendedTaskReasonForSelection({
		isChineseUi,
		isManualFocus: Boolean(
			manualFocusTaskId && selectedTask?.task_id === manualFocusTaskId,
		),
		recommendedTaskId,
		selectedTask,
		taskDisplayState,
		tasks,
	});
	const finalPreviewState = finalPreviewStateForWorkbench({
		activeBundle,
		evidenceItems,
		isChineseUi,
		riskItems,
	});
	const decisionDockState = decisionDockStateForWorkbench({
		blockedExplanation,
		canGenerateResult,
		finalPreviewState,
		focusReason,
		nextStepHint,
		primaryAction,
		recommendedTaskId,
		riskItems,
		selectedTaskState: selectedTaskFocusState,
	});
	const finalResultState = finalPreviewState;
	const recommendedTaskReason = focusReason;

	return {
		activeBundle,
		canGenerateResult,
		changedFiles,
		displayTitle,
		evidenceItems,
		fallbackPlan,
		advancedMeta,
		blockedExplanation,
		decisionDockState,
		finalPreviewState,
		focusReason,
		missionHeaderState,
		missionStage,
		missionProgress,
		nextStepHint,
		isPlanReview,
		pendingBundle,
		phaseMapItems,
		phaseGroups,
		planningMetadata,
		primaryAction,
		queuedTasks,
		readyTasks,
		recommendedTaskId,
		riskItems,
		runningTasks,
		selectedTask,
		setSelectedTaskId,
		recommendedTaskReason,
		taskDisplayState,
		taskDisplayStates,
		tasks,
		userFacingResult,
		view,
		nextStep: nextStepHint,
		finalResultState,
	};
}
