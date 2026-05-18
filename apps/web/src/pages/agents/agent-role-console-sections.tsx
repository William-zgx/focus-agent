import type { ReactNode } from "react";

import { asRecord, jsonPreview, roleLabel } from "./agent-role-console-utils";

type PanelHeaderProps = {
	eyebrow: ReactNode;
	title: ReactNode;
	meta: ReactNode;
};

type EmptyStateProps = {
	children: ReactNode;
};

type NoticeProps = {
	children: ReactNode;
};

type KeyValueRow = {
	label: ReactNode;
	value: ReactNode;
	note?: ReactNode;
};

type KeyValueListProps = {
	rows: KeyValueRow[];
};

type TrajectoryDetailsListProps<T> = {
	items: T[];
	getKey: (item: T, index: number) => string;
	getSummary: (
		item: T,
		index: number,
	) => {
		label: ReactNode;
		value: ReactNode;
	};
	empty?: ReactNode;
	limit?: number;
	wrap?: boolean;
};

type AgentRoleHeroProps = {
	isChineseUi: boolean;
	policyEnabled: boolean | undefined;
	memoryEnabled: boolean | undefined;
	autoPromoteOnMerge: boolean | undefined;
	capabilityCount: number | undefined;
	delegationEnabled: boolean | undefined;
	delegationEnforce: boolean | undefined;
	contextEnabled: boolean | undefined;
	artifactizeLongObservations: boolean | undefined;
	taskLedgerEnabled: boolean | undefined;
	criticGateEnforce: boolean | undefined;
};

type DecisionCard = Record<string, unknown>;

export function PanelHeader({ eyebrow, title, meta }: PanelHeaderProps) {
	return (
		<div className="fa-observability-panel-header">
			<div>
				<strong>{eyebrow}</strong>
				<h2>{title}</h2>
			</div>
			<span>{meta}</span>
		</div>
	);
}

export function EmptyState({ children }: EmptyStateProps) {
	return <div className="fa-observability-empty is-compact">{children}</div>;
}

export function InlineDangerNotice({ children }: NoticeProps) {
	return <div className="fa-inline-notice is-danger">{children}</div>;
}

export function KeyValueList({ rows }: KeyValueListProps) {
	return (
		<div className="fa-agent-role-model-list">
			{rows.map((row, index) => (
				<div
					className="fa-agent-role-model-row"
					key={String(row.label ?? index)}
				>
					<span>{row.label}</span>
					<strong>{row.value}</strong>
					{row.note ? <small>{row.note}</small> : null}
				</div>
			))}
		</div>
	);
}

export function RawJsonDetails({
	summary,
	value,
}: {
	summary: ReactNode;
	value: unknown;
}) {
	return (
		<details className="fa-observability-raw-toggle">
			<summary>{summary}</summary>
			<pre>{jsonPreview(value)}</pre>
		</details>
	);
}

export function TrajectoryDetailsList<T>({
	items,
	getKey,
	getSummary,
	empty,
	limit,
	wrap = true,
}: TrajectoryDetailsListProps<T>) {
	const visibleItems = limit ? items.slice(0, limit) : items;
	const content = (
		<>
			{visibleItems.map((item, index) => {
				const summary = getSummary(item, index);
				return (
					<details
						className="fa-agent-role-trajectory-row"
						key={getKey(item, index)}
					>
						<summary>
							<span>{summary.label}</span>
							<strong>{summary.value}</strong>
						</summary>
						<pre>{jsonPreview(item)}</pre>
					</details>
				);
			})}
			{!items.length && empty ? <EmptyState>{empty}</EmptyState> : null}
		</>
	);

	return wrap ? (
		<div className="fa-agent-role-trajectory-list">{content}</div>
	) : (
		content
	);
}

export function RoleDecisionCards({
	decisions,
}: {
	decisions: DecisionCard[];
}) {
	return (
		<div className="fa-agent-role-decision-list">
			{decisions.map((decision, index) => (
				<div
					className="fa-agent-role-decision-card"
					key={`${decision.role}-${index}`}
				>
					<div>
						<span>{roleLabel(String(decision.role ?? "role"))}</span>
						<strong>{String(decision.model_id ?? "-")}</strong>
					</div>
					<p>{String(decision.rationale ?? "")}</p>
					<pre>{jsonPreview(decision.tool_governance ?? {})}</pre>
				</div>
			))}
		</div>
	);
}

export function ToolRouteDecisionCards({
	decisions,
}: {
	decisions: DecisionCard[];
}) {
	return (
		<div className="fa-agent-role-decision-list">
			{decisions.map((decision, index) => (
				<div
					className="fa-agent-role-decision-card"
					key={`route-${decision.name}-${index}`}
				>
					<div>
						<span>{String(decision.name ?? "tool")}</span>
						<strong>{String(decision.allowed ?? false)}</strong>
					</div>
					<p>{String(decision.reason ?? "")}</p>
				</div>
			))}
		</div>
	);
}

export function RoleTrajectoryList({
	items,
	empty,
}: {
	items: unknown[];
	empty: ReactNode;
}) {
	return (
		<div className="fa-agent-role-trajectory-list">
			{items.map((item, index) => {
				const record = asRecord(item);
				return (
					<details
						className="fa-agent-role-trajectory-row"
						key={`${record.turn_id}-${index}`}
					>
						<summary>
							<span>{String(record.turn_id ?? "turn")}</span>
							<strong>
								{String(record.route_reason ?? "role route plan")}
							</strong>
						</summary>
						<pre>{jsonPreview(record)}</pre>
					</details>
				);
			})}
			{!items.length ? <EmptyState>{empty}</EmptyState> : null}
		</div>
	);
}

export function AgentRoleHero({
	isChineseUi,
	policyEnabled,
	memoryEnabled,
	autoPromoteOnMerge,
	capabilityCount,
	delegationEnabled,
	delegationEnforce,
	contextEnabled,
	artifactizeLongObservations,
	taskLedgerEnabled,
	criticGateEnforce,
}: AgentRoleHeroProps) {
	return (
		<section className="fa-observability-hero fa-agent-role-hero">
			<div className="fa-observability-hero-copy">
				<p className="fa-observability-kicker">
					{isChineseUi ? "Agent 决策架构" : "Agent Decision Architecture"}
				</p>
				<h1>{isChineseUi ? "Agent 治理控制台" : "Agent Governance Console"}</h1>
				<p className="fa-observability-hero-text">
					{isChineseUi
						? "查看角色路由、Memory Curator 分支语义保护，以及 Skill Scout / Tool Router 的能力注册表与实际决策。"
						: "Inspect role routing, Memory Curator branch semantics, and Skill Scout / Tool Router capability decisions."}
				</p>
			</div>
			<div className="fa-observability-hero-grid fa-agent-role-policy-grid">
				<div className="fa-observability-stat-card">
					<span>{isChineseUi ? "状态" : "Status"}</span>
					<strong>{policyEnabled ? "enabled" : "dry-run off"}</strong>
					<p>
						{isChineseUi
							? "角色路由仍可独立预演"
							: "Role routing can still be previewed"}
					</p>
				</div>
				<div className="fa-observability-stat-card">
					<span>{isChineseUi ? "Memory Curator" : "Memory Curator"}</span>
					<strong>{memoryEnabled ? "enabled" : "disabled"}</strong>
					<p>{autoPromoteOnMerge ? "auto promote on merge" : "review only"}</p>
				</div>
				<div className="fa-observability-stat-card">
					<span>{isChineseUi ? "Capabilities" : "Capabilities"}</span>
					<strong>{capabilityCount ?? "-"}</strong>
					<p>
						{isChineseUi
							? "工具按角色、风险和能力注册"
							: "Tools are registered by role, risk, and capability"}
					</p>
				</div>
				<div className="fa-observability-stat-card">
					<span>{isChineseUi ? "Delegation" : "Delegation"}</span>
					<strong>{delegationEnabled ? "enabled" : "disabled"}</strong>
					<p>{delegationEnforce ? "enforce" : "observe"}</p>
				</div>
				<div className="fa-observability-stat-card">
					<span>{isChineseUi ? "Context v2" : "Context v2"}</span>
					<strong>{contextEnabled ? "enabled" : "disabled"}</strong>
					<p>
						{artifactizeLongObservations ? "artifact refs on" : "preview safe"}
					</p>
				</div>
				<div className="fa-observability-stat-card">
					<span>{isChineseUi ? "Task Ledger" : "Task Ledger"}</span>
					<strong>{taskLedgerEnabled ? "enabled" : "disabled"}</strong>
					<p>{criticGateEnforce ? "critic enforce" : "artifact observe"}</p>
				</div>
			</div>
		</section>
	);
}
