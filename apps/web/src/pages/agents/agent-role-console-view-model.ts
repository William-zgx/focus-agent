import type {
	FocusAgentContextPreviewResponse,
	FocusAgentRoleDryRunResponse,
	FocusAgentTaskLedgerPlanResponse,
	FocusAgentToolRouteResponse,
} from "@focus-agent/web-sdk";
import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import {
	useAgentArtifacts,
	useAgentCapabilities,
	useAgentContextArtifacts,
	useAgentContextDecisions,
	useAgentContextEvidence,
	useAgentContextPolicy,
	useAgentCriticVerdicts,
	useAgentDelegationPolicy,
	useAgentDelegationRuns,
	useAgentFeedbackTrend,
	useAgentMemoryCuratorDecisions,
	useAgentMemoryCuratorPolicy,
	useAgentModelRouterDecisions,
	useAgentModelRouterPolicy,
	useAgentReviewQueue,
	useAgentRoleDecisions,
	useAgentRolePolicy,
	useAgentSelfRepairFailures,
	useAgentSkillCatalog,
	useAgentSkillSelections,
	useAgentTaskLedgerPolicy,
	useAgentTaskLedgerRuns,
	useAgentToolRouteDecisions,
} from "./agent-role-console-hooks";
import {
	asArray,
	asRecord,
	DEFAULT_AVAILABLE_TOOLS,
	DEFAULT_DRY_RUN_MESSAGE,
	parseAvailableTools,
} from "./agent-role-console-utils";

export function useAgentRoleConsoleQueries() {
	const policy = useAgentRolePolicy();
	const decisions = useAgentRoleDecisions();
	const capabilities = useAgentCapabilities();
	const toolRouteDecisions = useAgentToolRouteDecisions();
	const memoryPolicy = useAgentMemoryCuratorPolicy();
	const memoryDecisions = useAgentMemoryCuratorDecisions();
	const delegationPolicy = useAgentDelegationPolicy();
	const delegationRuns = useAgentDelegationRuns();
	const modelRouterPolicy = useAgentModelRouterPolicy();
	const modelRouterDecisions = useAgentModelRouterDecisions();
	const selfRepairFailures = useAgentSelfRepairFailures();
	const reviewQueue = useAgentReviewQueue();
	const contextPolicy = useAgentContextPolicy();
	const contextDecisions = useAgentContextDecisions();
	const contextArtifacts = useAgentContextArtifacts();
	const contextEvidence = useAgentContextEvidence();
	const skillCatalog = useAgentSkillCatalog();
	const skillSelections = useAgentSkillSelections();
	const feedbackTrend = useAgentFeedbackTrend();
	const taskLedgerPolicy = useAgentTaskLedgerPolicy();
	const taskLedgerRuns = useAgentTaskLedgerRuns();
	const delegatedArtifacts = useAgentArtifacts();
	const criticVerdicts = useAgentCriticVerdicts();
	const roleModels = useMemo(
		() => Object.entries(policy.data?.role_models ?? {}),
		[policy.data?.role_models],
	);

	return {
		policy,
		decisions,
		capabilities,
		toolRouteDecisions,
		memoryPolicy,
		memoryDecisions,
		delegationPolicy,
		delegationRuns,
		modelRouterPolicy,
		modelRouterDecisions,
		selfRepairFailures,
		reviewQueue,
		contextPolicy,
		contextDecisions,
		contextArtifacts,
		contextEvidence,
		skillCatalog,
		skillSelections,
		feedbackTrend,
		taskLedgerPolicy,
		taskLedgerRuns,
		delegatedArtifacts,
		criticVerdicts,
		roleModels,
		recentDecisionItems: decisions.data?.items ?? [],
		capabilityItems: capabilities.data?.items ?? [],
		recentToolRouteItems: toolRouteDecisions.data?.items ?? [],
		recentMemoryItems: memoryDecisions.data?.items ?? [],
		recentDelegationRuns: delegationRuns.data?.items ?? [],
		recentModelRouteItems: modelRouterDecisions.data?.items ?? [],
		recentFailures: selfRepairFailures.data?.items ?? [],
		reviewQueueItems: reviewQueue.data?.items ?? [],
		recentContextDecisions: contextDecisions.data?.items ?? [],
		recentContextArtifacts: contextArtifacts.data?.items ?? [],
		recentContextEvidence: contextEvidence.data?.items ?? [],
		skillCatalogItems: skillCatalog.data?.items ?? [],
		recentSkillSelections: skillSelections.data?.items ?? [],
		recentTaskLedgerRuns: taskLedgerRuns.data?.items ?? [],
		recentDelegatedArtifacts: delegatedArtifacts.data?.items ?? [],
		recentCriticVerdicts: criticVerdicts.data?.items ?? [],
	};
}

export function useAgentRoleConsolePreviews() {
	const { client } = useFocusAgent();
	const [message, setMessage] = useState(DEFAULT_DRY_RUN_MESSAGE);
	const [availableTools, setAvailableTools] = useState(DEFAULT_AVAILABLE_TOOLS);
	const [toolRouteRole, setToolRouteRole] = useState("executor");
	const [toolRoutePolicy, setToolRoutePolicy] = useState("execution");
	const parsedAvailableTools = useMemo(
		() => parseAvailableTools(availableTools),
		[availableTools],
	);
	const dryRun = useMutation<FocusAgentRoleDryRunResponse, Error>({
		mutationFn: () =>
			client.dryRunAgentRoleRoute({
				message,
				scene: "role_routing_console",
				available_tools: parsedAvailableTools,
			}),
	});
	const toolRoute = useMutation<FocusAgentToolRouteResponse, Error>({
		mutationFn: () =>
			client.routeAgentTools({
				role: toolRouteRole,
				tool_policy: toolRoutePolicy,
				available_tools: parsedAvailableTools,
			}),
	});
	const contextPreview = useMutation<FocusAgentContextPreviewResponse, Error>({
		mutationFn: () =>
			client.previewAgentContext({
				prompt_mode: "execute",
				role: "executor",
				assembled_context: `${message}\n\n${availableTools.repeat(80)}`,
				state: {
					context_budget: {
						prompt_token_limit: 1200,
						chars_per_token: 1,
					},
					rolling_summary: message.repeat(20),
				},
			}),
	});
	const taskLedgerPreview = useMutation<
		FocusAgentTaskLedgerPlanResponse,
		Error
	>({
		mutationFn: () =>
			client.planAgentTaskLedger({
				message,
			}),
	});
	const dryRunPlan = asRecord(dryRun.data?.plan);
	const toolRoutePlan = asRecord(toolRoute.data?.plan);
	const contextPreviewDecision = asRecord(contextPreview.data?.decision);
	const taskLedgerPreviewLedger = asRecord(taskLedgerPreview.data?.ledger);

	return {
		message,
		setMessage,
		availableTools,
		setAvailableTools,
		toolRouteRole,
		setToolRouteRole,
		toolRoutePolicy,
		setToolRoutePolicy,
		dryRun,
		toolRoute,
		contextPreview,
		taskLedgerPreview,
		dryRunDecisions: asArray(dryRunPlan.decisions),
		toolRoutePlanDecisions: asArray(toolRoutePlan.decisions),
		contextPreviewBudget: asRecord(contextPreviewDecision.budget),
		contextPreviewPlan: asRecord(contextPreviewDecision.compression_plan),
		taskLedgerPreviewTasks: asArray(taskLedgerPreviewLedger.tasks),
	};
}
