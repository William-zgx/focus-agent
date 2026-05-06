import type { FocusAgentToolApprovalInterrupt } from "@focus-agent/web-sdk";

interface ToolApprovalCardProps {
	interrupt: FocusAgentToolApprovalInterrupt;
	isBusy?: boolean;
	isChineseUi?: boolean;
	isReadOnly?: boolean;
	errorMessage?: string;
	onDecide?: (
		interrupt: FocusAgentToolApprovalInterrupt,
		approved: boolean,
	) => void;
}

function formatApprovalArgs(args: Record<string, unknown>): string {
	try {
		return JSON.stringify(args, null, 2);
	} catch {
		return String(args);
	}
}

export function ToolApprovalCard({
	interrupt,
	isBusy = false,
	isChineseUi = false,
	isReadOnly = false,
	errorMessage,
	onDecide,
}: ToolApprovalCardProps) {
	const canAct = Boolean(onDecide) && !isReadOnly && !isBusy;
	const title = isChineseUi ? "工具执行需要审批" : "Tool approval required";
	const riskLabel = isChineseUi ? "风险" : "Risk";
	const argsLabel = isChineseUi ? "参数" : "Args";

	return (
		<article className="fa-tool-approval-card">
			<div className="fa-tool-approval-card-header">
				<div>
					<div className="fa-tool-approval-card-title">{title}</div>
					<div className="fa-tool-approval-card-meta">
						<code>{interrupt.tool_name}</code>
						<span>{interrupt.interrupt_id}</span>
					</div>
				</div>
				<span className="fa-tool-approval-card-badge">
					{riskLabel}: {interrupt.risk_level || "low"}
				</span>
			</div>
			<div className="fa-tool-approval-card-body">
				<span>{argsLabel}</span>
				<pre>{formatApprovalArgs(interrupt.redacted_args)}</pre>
			</div>
			{errorMessage ? (
				<div className="fa-tool-approval-card-error">{errorMessage}</div>
			) : null}
			<div className="fa-tool-approval-card-actions">
				<button
					className="fa-branch-action-button is-primary"
					disabled={!canAct}
					type="button"
					onClick={() => onDecide?.(interrupt, true)}
				>
					{isBusy
						? isChineseUi
							? "提交中..."
							: "Submitting..."
						: isChineseUi
							? "批准"
							: "Approve"}
				</button>
				<button
					className="fa-branch-action-button"
					disabled={!canAct}
					type="button"
					onClick={() => onDecide?.(interrupt, false)}
				>
					{isChineseUi ? "拒绝" : "Deny"}
				</button>
			</div>
		</article>
	);
}
