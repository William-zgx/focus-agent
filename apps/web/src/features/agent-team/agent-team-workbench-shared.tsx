import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { STATUS_TONES, statusLabel } from "./agent-team-workbench-utils";

export function StatusPill({ status }: { status: string }) {
	const { isChineseUi } = useShellUi();
	const tone = STATUS_TONES[status] ?? "neutral";
	return (
		<span className={`fa-agent-team-pill is-${tone}`}>
			{statusLabel(status, isChineseUi)}
		</span>
	);
}

export function EmptyList({ children }: { children: string }) {
	return <div className="fa-agent-team-empty">{children}</div>;
}

export function FieldList({ items }: { items?: string[] }) {
	if (!items?.length) return <EmptyList>—</EmptyList>;
	return (
		<ul className="fa-agent-team-list">
			{items.map((item) => (
				<li key={item}>{item}</li>
			))}
		</ul>
	);
}

export function HelpText({ children }: { children: string }) {
	const { isChineseUi } = useShellUi();
	return (
		<span
			aria-label={isChineseUi ? "说明" : "Help"}
			className="fa-agent-team-help-tip"
			role="img"
			{...tooltipProps(children)}
		/>
	);
}

export function WorkflowGuide({ compact = false }: { compact?: boolean }) {
	const { isChineseUi } = useShellUi();
	const summary = isChineseUi
		? "Mission Runner 会根据目标推导交付物、任务依赖和最终结果；分支线程只是辅助入口。"
		: "Mission Runner infers deliverables, task dependencies, and final results from the goal; branch threads are supporting links.";
	const steps = isChineseUi
		? [
				["目标", "描述结果", "说明要达成什么和已有上下文"],
				["DAG", "自动拆解", "按交付物生成任务和依赖"],
				["结果", "收束交付", "汇总依据、风险和最终回答"],
			]
		: [
				["Goal", "Describe outcome", "State the needed result and context"],
				["DAG", "Auto-plan", "Generate deliverable tasks and dependencies"],
				["Result", "Synthesize", "Collect evidence, risks, and final answer"],
			];

	return (
		<section
			className={`fa-agent-team-guide ${compact ? "is-compact" : ""}`.trim()}
		>
			<div className="fa-agent-team-guide-heading">
				<span>{isChineseUi ? "Mission Runner" : "Mission Runner"}</span>
				<strong {...tooltipProps(summary)}>
					{isChineseUi ? "从目标到可运行 DAG" : "From goal to runnable DAG"}
				</strong>
			</div>
			<div className="fa-agent-team-step-strip">
				{steps.map(([index, title, description]) => (
					<div
						className="fa-agent-team-step"
						key={index}
						{...tooltipProps(description)}
					>
						<span>{index}</span>
						<strong>{title}</strong>
					</div>
				))}
			</div>
		</section>
	);
}

export function StatusLegend() {
	const { isChineseUi } = useShellUi();
	const legendText = isChineseUi
		? "待开始：任务已创建但未执行；执行中：Agent 正在工作；已完成：产出和验证已回传；需要处理：存在风险或缺口。"
		: "Pending: task exists but has not run; Running: agent is working; Completed: outputs and evidence are returned; Needs attention: risk or gap needs handling.";
	return (
		<span className="fa-agent-team-legend-chip" {...tooltipProps(legendText)}>
			{isChineseUi ? "状态图例" : "Status legend"}
		</span>
	);
}
