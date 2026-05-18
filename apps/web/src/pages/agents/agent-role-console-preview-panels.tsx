import {
	EmptyState,
	InlineDangerNotice,
	PanelHeader,
	RoleDecisionCards,
	ToolRouteDecisionCards,
} from "./agent-role-console-sections";
import { errorMessage } from "./agent-role-console-utils";

type DecisionItem = Record<string, unknown>;

type PreviewMutationState = {
	data?: unknown;
	error: Error | null;
	isPending: boolean;
};

type RoleRoutingPreviewPanelProps = {
	availableTools: string;
	dryRun: PreviewMutationState;
	dryRunDecisions: DecisionItem[];
	isChineseUi: boolean;
	message: string;
	onAvailableToolsChange: (value: string) => void;
	onMessageChange: (value: string) => void;
	onRunDryRun: () => void;
};

type ToolRoutingPreviewPanelProps = {
	isChineseUi: boolean;
	onRouteTools: () => void;
	onToolRoutePolicyChange: (value: string) => void;
	onToolRouteRoleChange: (value: string) => void;
	toolRoute: PreviewMutationState;
	toolRoutePlanDecisions: DecisionItem[];
	toolRoutePolicy: string;
	toolRouteRole: string;
};

export function RoleRoutingPreviewPanel({
	availableTools,
	dryRun,
	dryRunDecisions,
	isChineseUi,
	message,
	onAvailableToolsChange,
	onMessageChange,
	onRunDryRun,
}: RoleRoutingPreviewPanelProps) {
	return (
		<div className="fa-observability-detail-panel fa-agent-role-panel">
			<PanelHeader
				eyebrow={isChineseUi ? "Dry run" : "Dry run"}
				meta={dryRun.isPending ? "running" : "preview only"}
				title={isChineseUi ? "路由预演" : "Routing Preview"}
			/>
			<div className="fa-agent-role-dry-run-form">
				<label className="fa-observability-filter fa-agent-role-field">
					<span>{isChineseUi ? "任务文本" : "Task text"}</span>
					<textarea
						value={message}
						onChange={(event) => onMessageChange(event.target.value)}
						rows={5}
					/>
				</label>
				<label className="fa-observability-filter fa-agent-role-field">
					<span>{isChineseUi ? "可用工具" : "Available tools"}</span>
					<input
						value={availableTools}
						onChange={(event) => onAvailableToolsChange(event.target.value)}
					/>
				</label>
				<div className="fa-observability-command-bar">
					<button
						className="fa-observability-preset is-primary"
						disabled={dryRun.isPending || !message.trim()}
						onClick={onRunDryRun}
						type="button"
					>
						{dryRun.isPending
							? isChineseUi
								? "预演中..."
								: "Running..."
							: isChineseUi
								? "预演路由"
								: "Dry Run Route"}
					</button>
				</div>
			</div>
			{dryRun.error ? (
				<InlineDangerNotice>
					{errorMessage(dryRun.error, "Dry-run request failed")}
				</InlineDangerNotice>
			) : null}
			{dryRun.data ? (
				<RoleDecisionCards decisions={dryRunDecisions} />
			) : (
				<EmptyState>
					{isChineseUi
						? "提交一次 dry-run 后，这里会展示路由决策。"
						: "Run a dry-run to inspect routing decisions here."}
				</EmptyState>
			)}
		</div>
	);
}

export function ToolRoutingPreviewPanel({
	isChineseUi,
	onRouteTools,
	onToolRoutePolicyChange,
	onToolRouteRoleChange,
	toolRoute,
	toolRoutePlanDecisions,
	toolRoutePolicy,
	toolRouteRole,
}: ToolRoutingPreviewPanelProps) {
	return (
		<div className="fa-observability-detail-panel fa-agent-role-panel">
			<PanelHeader
				eyebrow={isChineseUi ? "Tool Router" : "Tool Router"}
				meta={toolRoute.isPending ? "routing" : "enforced plan"}
				title={isChineseUi ? "能力路由预演" : "Capability Routing"}
			/>
			<div className="fa-agent-role-dry-run-form">
				<label className="fa-observability-filter fa-agent-role-field">
					<span>{isChineseUi ? "角色" : "Role"}</span>
					<select
						value={toolRouteRole}
						onChange={(event) => onToolRouteRoleChange(event.target.value)}
					>
						<option value="executor">executor</option>
						<option value="critic">critic</option>
						<option value="planner">planner</option>
						<option value="memory_curator">memory_curator</option>
						<option value="skill_scout">skill_scout</option>
					</select>
				</label>
				<label className="fa-observability-filter fa-agent-role-field">
					<span>{isChineseUi ? "工具策略" : "Tool policy"}</span>
					<select
						value={toolRoutePolicy}
						onChange={(event) => onToolRoutePolicyChange(event.target.value)}
					>
						<option value="execution">execution</option>
						<option value="workspace_lookup">workspace_lookup</option>
						<option value="live_web_research">live_web_research</option>
						<option value="direct_answer">direct_answer</option>
					</select>
				</label>
				<div className="fa-observability-command-bar">
					<button
						className="fa-observability-preset is-primary"
						disabled={toolRoute.isPending}
						onClick={onRouteTools}
						type="button"
					>
						{toolRoute.isPending
							? isChineseUi
								? "路由中..."
								: "Routing..."
							: isChineseUi
								? "预演工具路由"
								: "Route Tools"}
					</button>
				</div>
			</div>
			{toolRoute.error ? (
				<InlineDangerNotice>
					{errorMessage(toolRoute.error, "Tool route request failed")}
				</InlineDangerNotice>
			) : null}
			{toolRoute.data ? (
				<ToolRouteDecisionCards decisions={toolRoutePlanDecisions} />
			) : (
				<EmptyState>
					{isChineseUi
						? "运行一次工具路由后，这里会展示 allow/deny 决策。"
						: "Run tool routing to inspect allow/deny decisions."}
				</EmptyState>
			)}
		</div>
	);
}
