import {
	EmptyState,
	InlineDangerNotice,
	KeyValueList,
	PanelHeader,
	RawJsonDetails,
	TrajectoryDetailsList,
} from "./agent-role-console-sections";
import { asRecord, errorMessage, roleLabel } from "./agent-role-console-utils";

type DecisionItem = Record<string, unknown>;
type TrajectoryItem = unknown;
type RoleModelEntry = [string, string | null | undefined];

type PreviewMutationState = {
	data?: unknown;
	error: Error | null;
	isPending: boolean;
};

type RolePolicyData = {
	enabled?: boolean;
};

type MemoryPolicyData = {
	auto_promote_on_merge?: boolean;
	conflict_strategy?: string | null;
	enabled?: boolean;
};

type TaskLedgerPolicyData = {
	artifact_synthesis_enabled?: boolean;
	critic_gate_enabled?: boolean;
	critic_gate_enforce?: boolean;
	enabled?: boolean;
};

type ContextPolicyData = {
	artifact_min_chars?: number;
	enabled?: boolean;
	role_views_enabled?: boolean;
	tokenizer_mode?: string | null;
};

type RoleModelMappingPanelProps = {
	isChineseUi: boolean;
	policyData: RolePolicyData | undefined;
	policyError: Error | null;
	policyIsLoading: boolean;
	roleModels: RoleModelEntry[];
};

type MemoryCuratorPanelProps = {
	isChineseUi: boolean;
	memoryPolicyData: MemoryPolicyData | undefined;
	memoryPolicyError: Error | null;
	memoryPolicyIsLoading: boolean;
	recentMemoryItems: TrajectoryItem[];
};

type TaskLedgerPanelProps = {
	isChineseUi: boolean;
	message: string;
	onPreviewTaskLedger: () => void;
	recentTaskLedgerRuns: TrajectoryItem[];
	taskLedgerPolicyData: TaskLedgerPolicyData | undefined;
	taskLedgerPolicyError: Error | null;
	taskLedgerPreview: PreviewMutationState;
	taskLedgerPreviewTasks: DecisionItem[];
	taskLedgerTrajectoryAvailable: boolean | undefined;
};

type DelegatedArtifactsPanelProps = {
	delegatedArtifactsTrajectoryAvailable: boolean | undefined;
	isChineseUi: boolean;
	recentDelegatedArtifacts: TrajectoryItem[];
};

type ContextPolicyPanelProps = {
	contextPolicyData: ContextPolicyData | undefined;
	contextPolicyError: Error | null;
	contextPreview: PreviewMutationState;
	contextPreviewBudget: Record<string, unknown>;
	contextPreviewPlan: Record<string, unknown>;
	isChineseUi: boolean;
	onPreviewContext: () => void;
};

export function RoleModelMappingPanel({
	isChineseUi,
	policyData,
	policyError,
	policyIsLoading,
	roleModels,
}: RoleModelMappingPanelProps) {
	return (
		<div className="fa-observability-list-panel fa-agent-role-panel">
			<PanelHeader
				eyebrow={isChineseUi ? "Policy" : "Policy"}
				meta={policyIsLoading ? "loading" : `${roleModels.length} roles`}
				title={isChineseUi ? "角色模型映射" : "Role Model Mapping"}
			/>
			{policyError ? (
				<InlineDangerNotice>
					{errorMessage(policyError, "Failed to load role policy")}
				</InlineDangerNotice>
			) : null}
			<KeyValueList
				rows={roleModels.map(([role, model]) => ({
					label: roleLabel(role),
					value: model ?? "-",
				}))}
			/>
			<RawJsonDetails
				summary={isChineseUi ? "查看完整 policy JSON" : "View full policy JSON"}
				value={policyData ?? {}}
			/>
		</div>
	);
}

export function MemoryCuratorPanel({
	isChineseUi,
	memoryPolicyData,
	memoryPolicyError,
	memoryPolicyIsLoading,
	recentMemoryItems,
}: MemoryCuratorPanelProps) {
	return (
		<div className="fa-observability-list-panel fa-agent-role-panel">
			<PanelHeader
				eyebrow={isChineseUi ? "Memory Curator" : "Memory Curator"}
				meta={
					memoryPolicyIsLoading
						? "loading"
						: (memoryPolicyData?.conflict_strategy ?? "needs_review")
				}
				title={isChineseUi ? "分支语义保护" : "Branch Semantic Guard"}
			/>
			{memoryPolicyError ? (
				<InlineDangerNotice>
					{errorMessage(
						memoryPolicyError,
						"Failed to load memory curator policy",
					)}
				</InlineDangerNotice>
			) : null}
			<KeyValueList
				rows={[
					{
						label: isChineseUi ? "启用状态" : "Enabled",
						value: String(memoryPolicyData?.enabled ?? false),
					},
					{
						label: isChineseUi ? "合并自动提升" : "Auto promote on merge",
						value: String(memoryPolicyData?.auto_promote_on_merge ?? true),
					},
					{
						label: isChineseUi ? "冲突策略" : "Conflict strategy",
						value: memoryPolicyData?.conflict_strategy ?? "needs_review",
					},
				]}
			/>
			<TrajectoryDetailsList
				empty={
					isChineseUi
						? "还没有 memory curator trajectory 记录。"
						: "No memory curator trajectory records yet."
				}
				getKey={(_item, index) => `memory-${index}`}
				getSummary={(item) => {
					const record = asRecord(item);
					return {
						label: String(record.branch_id ?? record.turn_id ?? "memory"),
						value: String(record.status ?? "curator decision"),
					};
				}}
				items={recentMemoryItems}
				limit={5}
			/>
		</div>
	);
}

export function TaskLedgerPanel({
	isChineseUi,
	message,
	onPreviewTaskLedger,
	recentTaskLedgerRuns,
	taskLedgerPolicyData,
	taskLedgerPolicyError,
	taskLedgerPreview,
	taskLedgerPreviewTasks,
	taskLedgerTrajectoryAvailable,
}: TaskLedgerPanelProps) {
	return (
		<div className="fa-observability-list-panel fa-agent-role-panel">
			<PanelHeader
				eyebrow={isChineseUi ? "Task Ledger" : "Task Ledger"}
				meta={
					taskLedgerTrajectoryAvailable
						? `${recentTaskLedgerRuns.length} tasks`
						: "not available"
				}
				title={isChineseUi ? "任务账本与 DAG" : "Task DAG"}
			/>
			{taskLedgerPolicyError ? (
				<InlineDangerNotice>
					{errorMessage(
						taskLedgerPolicyError,
						"Failed to load task ledger policy",
					)}
				</InlineDangerNotice>
			) : null}
			<KeyValueList
				rows={[
					{
						label: isChineseUi ? "启用状态" : "Enabled",
						value: String(taskLedgerPolicyData?.enabled ?? false),
					},
					{
						label: isChineseUi ? "Artifact synthesis" : "Artifact synthesis",
						value: String(
							taskLedgerPolicyData?.artifact_synthesis_enabled ?? false,
						),
					},
					{
						label: isChineseUi ? "Critic gate" : "Critic gate",
						value: taskLedgerPolicyData?.critic_gate_enforce
							? "enforce"
							: String(taskLedgerPolicyData?.critic_gate_enabled ?? false),
					},
				]}
			/>
			<div className="fa-observability-command-bar">
				<button
					className="fa-observability-preset is-primary"
					disabled={taskLedgerPreview.isPending || !message.trim()}
					onClick={onPreviewTaskLedger}
					type="button"
				>
					{taskLedgerPreview.isPending
						? isChineseUi
							? "预览中..."
							: "Planning..."
						: isChineseUi
							? "预览任务账本"
							: "Preview Ledger"}
				</button>
			</div>
			{taskLedgerPreview.error ? (
				<InlineDangerNotice>
					{errorMessage(taskLedgerPreview.error, "Task ledger preview failed")}
				</InlineDangerNotice>
			) : null}
			{taskLedgerPreview.data ? (
				<TrajectoryDetailsList
					getKey={(_item, index) => `task-ledger-preview-${index}`}
					getSummary={(item) => ({
						label: String(item.role ?? item.task_id ?? "task"),
						value: String(item.status ?? "planned"),
					})}
					items={taskLedgerPreviewTasks}
				/>
			) : null}
			<TrajectoryDetailsList
				empty={
					!taskLedgerPreview.data
						? isChineseUi
							? "还没有 agent_task_ledger trajectory 记录。"
							: "No agent_task_ledger trajectory records yet."
						: null
				}
				getKey={(_item, index) => `task-ledger-${index}`}
				getSummary={(item) => {
					const record = asRecord(item);
					return {
						label: String(record.role ?? record.task_id ?? "task"),
						value: `${String(record.status ?? "planned")} / retry ${String(record.retry_count ?? 0)}`,
					};
				}}
				items={recentTaskLedgerRuns}
				limit={5}
			/>
		</div>
	);
}

export function DelegatedArtifactsPanel({
	delegatedArtifactsTrajectoryAvailable,
	isChineseUi,
	recentDelegatedArtifacts,
}: DelegatedArtifactsPanelProps) {
	return (
		<div className="fa-observability-detail-panel fa-agent-role-panel">
			<PanelHeader
				eyebrow={isChineseUi ? "Delegated Artifacts" : "Delegated Artifacts"}
				meta={
					delegatedArtifactsTrajectoryAvailable
						? `${recentDelegatedArtifacts.length} artifacts`
						: "not available"
				}
				title={isChineseUi ? "产物交接" : "Artifact Handoff"}
			/>
			<TrajectoryDetailsList
				empty={
					isChineseUi
						? "还没有 delegated_artifacts trajectory 记录。"
						: "No delegated artifact records yet."
				}
				getKey={(_item, index) => `delegated-artifact-${index}`}
				getSummary={(item) => {
					const record = asRecord(item);
					return {
						label: String(record.kind ?? record.title ?? "artifact"),
						value: String(record.status ?? "draft"),
					};
				}}
				items={recentDelegatedArtifacts}
				limit={6}
				wrap={false}
			/>
		</div>
	);
}

export function ContextPolicyPanel({
	contextPolicyData,
	contextPolicyError,
	contextPreview,
	contextPreviewBudget,
	contextPreviewPlan,
	isChineseUi,
	onPreviewContext,
}: ContextPolicyPanelProps) {
	return (
		<div className="fa-observability-list-panel fa-agent-role-panel">
			<PanelHeader
				eyebrow={
					isChineseUi ? "Context Engineering v2" : "Context Engineering v2"
				}
				meta={contextPolicyData?.enabled ? "enabled" : "disabled"}
				title={isChineseUi ? "长上下文压缩策略" : "Long Context Policy"}
			/>
			{contextPolicyError ? (
				<InlineDangerNotice>
					{errorMessage(contextPolicyError, "Failed to load context policy")}
				</InlineDangerNotice>
			) : null}
			<KeyValueList
				rows={[
					{
						label: isChineseUi ? "Tokenizer" : "Tokenizer",
						value: contextPolicyData?.tokenizer_mode ?? "chars_fallback",
					},
					{
						label: isChineseUi ? "Artifact 阈值" : "Artifact threshold",
						value: contextPolicyData?.artifact_min_chars ?? 12000,
					},
					{
						label: isChineseUi ? "角色视图" : "Role views",
						value: String(contextPolicyData?.role_views_enabled ?? false),
					},
				]}
			/>
			<div className="fa-observability-command-bar">
				<button
					className="fa-observability-preset is-primary"
					disabled={contextPreview.isPending}
					onClick={onPreviewContext}
					type="button"
				>
					{contextPreview.isPending
						? isChineseUi
							? "预览中..."
							: "Previewing..."
						: isChineseUi
							? "预览压缩决策"
							: "Preview Context"}
				</button>
			</div>
			{contextPreview.error ? (
				<InlineDangerNotice>
					{errorMessage(contextPreview.error, "Context preview request failed")}
				</InlineDangerNotice>
			) : null}
			{contextPreview.data ? (
				<KeyValueList
					rows={[
						{
							label: isChineseUi ? "Prompt chars" : "Prompt chars",
							value: String(contextPreviewBudget.prompt_chars ?? 0),
						},
						{
							label: isChineseUi ? "Over budget" : "Over budget",
							value: String(contextPreviewBudget.over_budget_chars ?? 0),
						},
						{
							label: isChineseUi ? "Saved chars" : "Saved chars",
							value: String(contextPreviewPlan.estimated_saved_chars ?? 0),
						},
					]}
				/>
			) : (
				<EmptyState>
					{isChineseUi
						? "运行一次预览后，这里会展示预算和压缩结果。"
						: "Run a preview to inspect budget and compression output."}
				</EmptyState>
			)}
		</div>
	);
}
