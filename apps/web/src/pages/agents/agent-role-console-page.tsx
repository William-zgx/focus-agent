import { useShellUi } from "@/app/shell/shell-ui-context";

import {
	ContextPolicyPanel,
	DelegatedArtifactsPanel,
	MemoryCuratorPanel,
	RoleModelMappingPanel,
	TaskLedgerPanel,
} from "./agent-role-console-policy-panels";
import { OperationsGovernancePanels } from "./agent-role-console-operations-panels";
import {
	RoleRoutingPreviewPanel,
	ToolRoutingPreviewPanel,
} from "./agent-role-console-preview-panels";
import { AgentRoleHero } from "./agent-role-console-sections";
import {
	CapabilityRegistryPanel,
	ContextArtifactsPanel,
	ContextDecisionsPanel,
	CriticGatePanel,
	DelegationModelRouterPanels,
	RecentDecisionRecordsPanel,
	RepairReviewQueuePanels,
	ToolRouterTrajectoryPanel,
} from "./agent-role-console-trajectory-panels";
import {
	useAgentRoleConsolePreviews,
	useAgentRoleConsoleQueries,
} from "./agent-role-console-view-model";

export function AgentRoleConsolePage() {
	const { isChineseUi } = useShellUi();
	const queries = useAgentRoleConsoleQueries();
	const previews = useAgentRoleConsolePreviews();
	const recentDelegatedArtifacts =
		previews.taskLedgerPreview.data?.artifacts ??
		queries.recentDelegatedArtifacts;

	return (
		<div className="fa-observability-layout fa-agent-role-console">
			<AgentRoleHero
				artifactizeLongObservations={
					queries.contextPolicy.data?.artifactize_long_observations
				}
				autoPromoteOnMerge={queries.memoryPolicy.data?.auto_promote_on_merge}
				capabilityCount={queries.capabilities.data?.count}
				contextEnabled={queries.contextPolicy.data?.enabled}
				criticGateEnforce={queries.taskLedgerPolicy.data?.critic_gate_enforce}
				delegationEnabled={queries.delegationPolicy.data?.enabled}
				delegationEnforce={queries.delegationPolicy.data?.enforce}
				isChineseUi={isChineseUi}
				memoryEnabled={queries.memoryPolicy.data?.enabled}
				policyEnabled={queries.policy.data?.enabled}
				taskLedgerEnabled={queries.taskLedgerPolicy.data?.enabled}
			/>

			<section className="fa-agent-role-grid">
				<RoleModelMappingPanel
					isChineseUi={isChineseUi}
					policyData={queries.policy.data}
					policyError={queries.policy.error}
					policyIsLoading={queries.policy.isLoading}
					roleModels={queries.roleModels}
				/>
				<RoleRoutingPreviewPanel
					availableTools={previews.availableTools}
					dryRun={previews.dryRun}
					dryRunDecisions={previews.dryRunDecisions}
					isChineseUi={isChineseUi}
					message={previews.message}
					onAvailableToolsChange={previews.setAvailableTools}
					onMessageChange={previews.setMessage}
					onRunDryRun={() => previews.dryRun.mutate()}
				/>
			</section>

			<section className="fa-agent-role-grid">
				<MemoryCuratorPanel
					isChineseUi={isChineseUi}
					memoryPolicyData={queries.memoryPolicy.data}
					memoryPolicyError={queries.memoryPolicy.error}
					memoryPolicyIsLoading={queries.memoryPolicy.isLoading}
					recentMemoryItems={queries.recentMemoryItems}
				/>
				<ToolRoutingPreviewPanel
					isChineseUi={isChineseUi}
					onRouteTools={() => previews.toolRoute.mutate()}
					onToolRoutePolicyChange={previews.setToolRoutePolicy}
					onToolRouteRoleChange={previews.setToolRouteRole}
					toolRoute={previews.toolRoute}
					toolRoutePlanDecisions={previews.toolRoutePlanDecisions}
					toolRoutePolicy={previews.toolRoutePolicy}
					toolRouteRole={previews.toolRouteRole}
				/>
			</section>

			<DelegationModelRouterPanels
				delegationTrajectoryAvailable={
					queries.delegationRuns.data?.trajectory_available
				}
				isChineseUi={isChineseUi}
				modelRouterEnabled={queries.modelRouterPolicy.data?.enabled}
				modelRouterMode={queries.modelRouterPolicy.data?.mode}
				modelRouterRoleModels={queries.modelRouterPolicy.data?.role_models}
				recentDelegationRuns={queries.recentDelegationRuns}
				recentModelRouteItems={queries.recentModelRouteItems}
			/>

			<section className="fa-agent-role-grid">
				<TaskLedgerPanel
					isChineseUi={isChineseUi}
					message={previews.message}
					onPreviewTaskLedger={() => previews.taskLedgerPreview.mutate()}
					recentTaskLedgerRuns={queries.recentTaskLedgerRuns}
					taskLedgerPolicyData={queries.taskLedgerPolicy.data}
					taskLedgerPolicyError={queries.taskLedgerPolicy.error}
					taskLedgerPreview={previews.taskLedgerPreview}
					taskLedgerPreviewTasks={previews.taskLedgerPreviewTasks}
					taskLedgerTrajectoryAvailable={
						queries.taskLedgerRuns.data?.trajectory_available
					}
				/>
				<DelegatedArtifactsPanel
					delegatedArtifactsTrajectoryAvailable={
						queries.delegatedArtifacts.data?.trajectory_available
					}
					isChineseUi={isChineseUi}
					recentDelegatedArtifacts={recentDelegatedArtifacts}
				/>
			</section>

			<CriticGatePanel
				criticTrajectoryAvailable={
					queries.criticVerdicts.data?.trajectory_available
				}
				criticVerdictCount={queries.criticVerdicts.data?.count}
				isChineseUi={isChineseUi}
				recentCriticVerdicts={queries.recentCriticVerdicts}
			/>

			<RepairReviewQueuePanels
				isChineseUi={isChineseUi}
				recentFailures={queries.recentFailures}
				reviewQueueItems={queries.reviewQueueItems}
				reviewQueueTrajectoryAvailable={
					queries.reviewQueue.data?.trajectory_available
				}
				selfRepairTrajectoryAvailable={
					queries.selfRepairFailures.data?.trajectory_available
				}
			/>

			<section className="fa-agent-role-grid">
				<ContextPolicyPanel
					contextPolicyData={queries.contextPolicy.data}
					contextPolicyError={queries.contextPolicy.error}
					contextPreview={previews.contextPreview}
					contextPreviewBudget={previews.contextPreviewBudget}
					contextPreviewPlan={previews.contextPreviewPlan}
					isChineseUi={isChineseUi}
					onPreviewContext={() => previews.contextPreview.mutate()}
				/>
				<ContextArtifactsPanel
					contextArtifactsTrajectoryAvailable={
						queries.contextArtifacts.data?.trajectory_available
					}
					isChineseUi={isChineseUi}
					recentContextArtifacts={queries.recentContextArtifacts}
				/>
			</section>

			<CapabilityRegistryPanel
				capabilitiesError={queries.capabilities.error}
				capabilitiesIsLoading={queries.capabilities.isLoading}
				capabilityItems={queries.capabilityItems}
				isChineseUi={isChineseUi}
			/>

			<OperationsGovernancePanels
				contextEvidence={queries.recentContextEvidence}
				contextEvidenceError={queries.contextEvidence.error}
				feedbackTrend={queries.feedbackTrend.data}
				feedbackTrendError={queries.feedbackTrend.error}
				isChineseUi={isChineseUi}
				skillCatalogItems={queries.skillCatalogItems}
				skillSelections={queries.recentSkillSelections}
				skillSelectionsError={queries.skillSelections.error}
			/>

			<ContextDecisionsPanel
				contextDecisionCount={queries.contextDecisions.data?.count}
				contextDecisionsTrajectoryAvailable={
					queries.contextDecisions.data?.trajectory_available
				}
				isChineseUi={isChineseUi}
				recentContextDecisions={queries.recentContextDecisions}
			/>

			<ToolRouterTrajectoryPanel
				isChineseUi={isChineseUi}
				recentToolRouteItems={queries.recentToolRouteItems}
				toolRouteDecisionCount={queries.toolRouteDecisions.data?.count}
				toolRouteTrajectoryAvailable={
					queries.toolRouteDecisions.data?.trajectory_available
				}
			/>

			<RecentDecisionRecordsPanel
				decisionCount={queries.decisions.data?.count}
				decisionsTrajectoryAvailable={
					queries.decisions.data?.trajectory_available
				}
				decisionsTrajectoryError={queries.decisions.data?.trajectory_error}
				isChineseUi={isChineseUi}
				recentDecisionItems={queries.recentDecisionItems}
			/>
		</div>
	);
}
