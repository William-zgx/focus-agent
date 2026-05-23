import {
	EmptyState,
	InlineDangerNotice,
	KeyValueList,
	PanelHeader,
	RoleTrajectoryList,
	TrajectoryDetailsList,
} from "./agent-role-console-sections";
import {
	asStringArray,
	errorMessage,
	roleLabel,
} from "./agent-role-console-utils";

type CapabilityItem = {
	name: string;
	allowed_roles: string[];
	toolset?: string | null;
	risk_level: string;
};

type RoleModelRows = Record<string, string | null | undefined>;
type TrajectoryItem = Record<string, unknown>;

type DelegationModelRouterPanelsProps = {
	isChineseUi: boolean;
	delegationTrajectoryAvailable: boolean | undefined;
	modelRouterEnabled: boolean | undefined;
	modelRouterMode: string | null | undefined;
	modelRouterRoleModels: RoleModelRows | undefined;
	recentDelegationRuns: TrajectoryItem[];
	recentModelRouteItems: TrajectoryItem[];
};

type CriticGatePanelProps = {
	isChineseUi: boolean;
	criticTrajectoryAvailable: boolean | undefined;
	criticVerdictCount: number | undefined;
	recentCriticVerdicts: TrajectoryItem[];
};

type RepairReviewQueuePanelsProps = {
	isChineseUi: boolean;
	reviewQueueItems: TrajectoryItem[];
	reviewQueueTrajectoryAvailable: boolean | undefined;
	recentFailures: TrajectoryItem[];
	selfRepairTrajectoryAvailable: boolean | undefined;
};

type ContextArtifactsPanelProps = {
	isChineseUi: boolean;
	contextArtifactsTrajectoryAvailable: boolean | undefined;
	recentContextArtifacts: TrajectoryItem[];
};

type CapabilityRegistryPanelProps = {
	capabilityItems: CapabilityItem[];
	capabilitiesError: Error | null;
	capabilitiesIsLoading: boolean;
	isChineseUi: boolean;
};

type ContextDecisionsPanelProps = {
	contextDecisionCount: number | undefined;
	contextDecisionsTrajectoryAvailable: boolean | undefined;
	isChineseUi: boolean;
	recentContextDecisions: TrajectoryItem[];
};

type ToolRouterTrajectoryPanelProps = {
	isChineseUi: boolean;
	recentToolRouteItems: TrajectoryItem[];
	toolRouteDecisionCount: number | undefined;
	toolRouteTrajectoryAvailable: boolean | undefined;
};

type RecentDecisionRecordsPanelProps = {
	decisionsTrajectoryAvailable: boolean | undefined;
	decisionsTrajectoryError: string | null | undefined;
	decisionCount: number | undefined;
	isChineseUi: boolean;
	recentDecisionItems: unknown[];
};

export function DelegationModelRouterPanels({
	isChineseUi,
	delegationTrajectoryAvailable,
	modelRouterEnabled,
	modelRouterMode,
	modelRouterRoleModels,
	recentDelegationRuns,
	recentModelRouteItems,
}: DelegationModelRouterPanelsProps) {
	return (
		<section className="fa-agent-role-grid">
			<div className="fa-observability-list-panel fa-agent-role-panel">
				<PanelHeader
					eyebrow={isChineseUi ? "Delegation Runs" : "Delegation Runs"}
					meta={
						delegationTrajectoryAvailable
							? `${recentDelegationRuns.length} runs`
							: "not available"
					}
					title={isChineseUi ? "多 Agent 执行轨迹" : "Multi-Agent Execution"}
				/>
				<TrajectoryDetailsList
					empty={
						isChineseUi
							? "还没有 agent_delegation_plan 记录。"
							: "No agent_delegation_plan records yet."
					}
					getKey={(_item, index) => `delegation-${index}`}
					getSummary={(item) => ({
						label: String(item.role ?? item.task_id ?? "role"),
						value: String(item.status ?? "planned"),
					})}
					items={recentDelegationRuns}
					limit={6}
				/>
			</div>

			<div className="fa-observability-detail-panel fa-agent-role-panel">
				<PanelHeader
					eyebrow={isChineseUi ? "Model Router" : "Model Router"}
					meta={modelRouterEnabled ? modelRouterMode : "disabled"}
					title={
						isChineseUi ? "成本 / 质量 / 延迟路由" : "Cost / Quality / Latency"
					}
				/>
				<KeyValueList
					rows={Object.entries(modelRouterRoleModels ?? {}).map(
						([role, model]) => ({
							label: roleLabel(role),
							value: model ?? "-",
						}),
					)}
				/>
				<TrajectoryDetailsList
					getKey={(_item, index) => `model-route-${index}`}
					getSummary={(item) => ({
						label: String(item.role ?? "executor"),
						value: String(
							item.effective_model ?? item.recommended_model ?? "-",
						),
					})}
					items={recentModelRouteItems}
					limit={4}
				/>
			</div>
		</section>
	);
}

export function CriticGatePanel({
	isChineseUi,
	criticTrajectoryAvailable,
	criticVerdictCount,
	recentCriticVerdicts,
}: CriticGatePanelProps) {
	return (
		<section className="fa-observability-detail-block fa-agent-role-trajectory">
			<PanelHeader
				eyebrow={isChineseUi ? "Critic Gate" : "Critic Gate"}
				meta={
					criticTrajectoryAvailable
						? `${criticVerdictCount} verdicts`
						: "not available"
				}
				title={isChineseUi ? "产物验收结果" : "Artifact Verdicts"}
			/>
			<TrajectoryDetailsList
				empty={
					isChineseUi
						? "还没有 critic_gate_result trajectory 记录。"
						: "No critic gate verdict records yet."
				}
				getKey={(_item, index) => `critic-gate-${index}`}
				getSummary={(item) => ({
					label: String(item.turn_id ?? "turn"),
					value: String(item.verdict ?? "skipped"),
				})}
				items={recentCriticVerdicts}
				limit={6}
				wrap={false}
			/>
		</section>
	);
}

export function RepairReviewQueuePanels({
	isChineseUi,
	reviewQueueItems,
	reviewQueueTrajectoryAvailable,
	recentFailures,
	selfRepairTrajectoryAvailable,
}: RepairReviewQueuePanelsProps) {
	return (
		<section className="fa-agent-role-grid">
			<div className="fa-observability-list-panel fa-agent-role-panel">
				<PanelHeader
					eyebrow={isChineseUi ? "Self Repair" : "Self Repair"}
					meta={
						selfRepairTrajectoryAvailable
							? `${recentFailures.length} failures`
							: "not available"
					}
					title={isChineseUi ? "失败归因与候选样本" : "Failure Triage"}
				/>
				<TrajectoryDetailsList
					empty={
						isChineseUi
							? "还没有 agent failure 记录。"
							: "No agent failure records yet."
					}
					getKey={(_item, index) => `failure-${index}`}
					getSummary={(item) => ({
						label: String(item.failure_type ?? "failure"),
						value: String(item.failed_role ?? "role"),
					})}
					items={recentFailures}
					limit={5}
					wrap={false}
				/>
			</div>

			<div className="fa-observability-detail-panel fa-agent-role-panel">
				<PanelHeader
					eyebrow={isChineseUi ? "Review Queue" : "Review Queue"}
					meta={
						reviewQueueTrajectoryAvailable
							? `${reviewQueueItems.length} items`
							: "not available"
					}
					title={isChineseUi ? "人工干预队列" : "Human Review Queue"}
				/>
				<TrajectoryDetailsList
					empty={
						isChineseUi
							? "还没有待人工确认的治理项。"
							: "No pending governance review items."
					}
					getKey={(_item, index) => `review-${index}`}
					getSummary={(item) => ({
						label: String(item.item_type ?? "review"),
						value: String(item.status ?? "pending"),
					})}
					items={reviewQueueItems}
					limit={5}
					wrap={false}
				/>
			</div>
		</section>
	);
}

export function ContextArtifactsPanel({
	isChineseUi,
	contextArtifactsTrajectoryAvailable,
	recentContextArtifacts,
}: ContextArtifactsPanelProps) {
	return (
		<div className="fa-observability-detail-panel fa-agent-role-panel">
			<PanelHeader
				eyebrow={isChineseUi ? "Context Artifacts" : "Context Artifacts"}
				meta={
					contextArtifactsTrajectoryAvailable
						? `${recentContextArtifacts.length} refs`
						: "not available"
				}
				title={isChineseUi ? "Artifact 化证据" : "Artifactized Evidence"}
			/>
			<TrajectoryDetailsList
				empty={
					isChineseUi
						? "还没有 context artifact trajectory 记录。"
						: "No context artifact trajectory records yet."
				}
				getKey={(_item, index) => `context-artifact-${index}`}
				getSummary={(item) => ({
					label: String(item.title ?? item.artifact_id ?? "artifact"),
					value: String(item.source ?? "context"),
				})}
				items={recentContextArtifacts}
				limit={5}
				wrap={false}
			/>
		</div>
	);
}

export function CapabilityRegistryPanel({
	capabilityItems,
	capabilitiesError,
	capabilitiesIsLoading,
	isChineseUi,
}: CapabilityRegistryPanelProps) {
	return (
		<section className="fa-observability-detail-block fa-agent-role-trajectory">
			<PanelHeader
				eyebrow={isChineseUi ? "Capability Registry" : "Capability Registry"}
				meta={
					capabilitiesIsLoading ? "loading" : `${capabilityItems.length} tools`
				}
				title={isChineseUi ? "工具能力注册表" : "Tool Capability Registry"}
			/>
			{capabilitiesError ? (
				<InlineDangerNotice>
					{errorMessage(capabilitiesError, "Failed to load capabilities")}
				</InlineDangerNotice>
			) : null}
			<KeyValueList
				rows={capabilityItems.map((item) => ({
					label: item.name,
					note: asStringArray(item.allowed_roles).join(", ") || "no roles",
					value: `${item.toolset ?? "core"} / ${item.risk_level}`,
				}))}
			/>
			{!capabilityItems.length ? (
				<EmptyState>
					{isChineseUi
						? "当前没有可展示的工具能力。"
						: "No tool capabilities to display."}
				</EmptyState>
			) : null}
		</section>
	);
}

export function ContextDecisionsPanel({
	contextDecisionCount,
	contextDecisionsTrajectoryAvailable,
	isChineseUi,
	recentContextDecisions,
}: ContextDecisionsPanelProps) {
	return (
		<section className="fa-observability-detail-block fa-agent-role-trajectory">
			<PanelHeader
				eyebrow={isChineseUi ? "Context Decisions" : "Context Decisions"}
				meta={
					contextDecisionsTrajectoryAvailable
						? `${contextDecisionCount} records`
						: "not available"
				}
				title={
					isChineseUi ? "最近上下文预算记录" : "Recent Context Budget Records"
				}
			/>
			<TrajectoryDetailsList
				empty={
					isChineseUi
						? "还没有 context_budget_decision trajectory 记录。"
						: "No context budget records yet."
				}
				getKey={(_item, index) => `context-decision-${index}`}
				getSummary={(item) => ({
					label: String(item.turn_id ?? "turn"),
					value: `${String(item.prompt_chars ?? 0)} / ${String(item.prompt_budget_chars ?? 0)} chars`,
				})}
				items={recentContextDecisions}
				limit={8}
				wrap={false}
			/>
		</section>
	);
}

export function ToolRouterTrajectoryPanel({
	isChineseUi,
	recentToolRouteItems,
	toolRouteDecisionCount,
	toolRouteTrajectoryAvailable,
}: ToolRouterTrajectoryPanelProps) {
	return (
		<section className="fa-observability-detail-block fa-agent-role-trajectory">
			<PanelHeader
				eyebrow={
					isChineseUi ? "Tool Router Trajectory" : "Tool Router Trajectory"
				}
				meta={
					toolRouteTrajectoryAvailable
						? `${toolRouteDecisionCount} records`
						: "not available"
				}
				title={isChineseUi ? "最近工具路由记录" : "Recent Tool Route Records"}
			/>
			<TrajectoryDetailsList
				empty={
					isChineseUi
						? "还没有 tool_route_plan trajectory 记录。"
						: "No tool_route_plan trajectory records yet."
				}
				getKey={(_item, index) => `tool-route-${index}`}
				getSummary={(item) => ({
					label: String(item.turn_id ?? "turn"),
					value: `${String(item.role ?? "role")} / ${String(item.tool_policy ?? "policy")}`,
				})}
				items={recentToolRouteItems}
				wrap={false}
			/>
		</section>
	);
}

export function RecentDecisionRecordsPanel({
	decisionsTrajectoryAvailable,
	decisionsTrajectoryError,
	decisionCount,
	isChineseUi,
	recentDecisionItems,
}: RecentDecisionRecordsPanelProps) {
	return (
		<section className="fa-observability-detail-block fa-agent-role-trajectory">
			<PanelHeader
				eyebrow={isChineseUi ? "Trajectory" : "Trajectory"}
				meta={
					decisionsTrajectoryAvailable
						? `${decisionCount} records`
						: "not available"
				}
				title={isChineseUi ? "最近决策记录" : "Recent Decision Records"}
			/>
			{decisionsTrajectoryError ? (
				<InlineDangerNotice>{decisionsTrajectoryError}</InlineDangerNotice>
			) : null}
			<RoleTrajectoryList
				empty={
					isChineseUi
						? "还没有带 role_route_plan 的 trajectory 记录。"
						: "No trajectory records with role_route_plan yet."
				}
				items={recentDecisionItems}
			/>
		</section>
	);
}
