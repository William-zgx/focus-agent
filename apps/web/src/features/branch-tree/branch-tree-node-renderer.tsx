import type { BranchTreeNode } from "@focus-agent/web-sdk";
import type { CSSProperties } from "react";

import type { BranchGraphNode } from "@/features/branch-tree/branch-tree-helpers";
import {
	branchStatusLabel,
	isBranchStale,
	roleColor,
	roleLabel,
	staleBranchLabel,
	staleBranchTooltip,
	statusBadgeTone,
	statusTone,
} from "@/features/branch-tree/branch-tree-helpers";
import { Badge } from "@/shared/ui/primitives";
import { tooltipProps } from "@/shared/ui/tooltip";

const focusRing =
	"focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fa-focus-ring)]";

type BranchTreeNodeRendererProps = {
	detailThreadId: string;
	graphNode: BranchGraphNode;
	isChineseUi: boolean;
	isContext: boolean;
	isDetailPinned: boolean;
	isFocused: boolean;
	isRouteThread: boolean;
	onOpenThread: (threadId: string) => void;
	onToggleDetailPinned: (
		node: BranchTreeNode,
		anchorElement: HTMLElement | null,
	) => void;
};

export function BranchTreeNodeRenderer({
	detailThreadId,
	graphNode,
	isChineseUi,
	isContext,
	isDetailPinned,
	isFocused,
	isRouteThread,
	onOpenThread,
	onToggleDetailPinned,
}: BranchTreeNodeRendererProps) {
	const node = graphNode.node;
	const tone = statusTone(node.branch_status);
	const isStale = isBranchStale(node);
	const detailsLabel = isChineseUi
		? `查看「${node.branch_name}」详情`
		: `Details for ${node.branch_name}`;

	return (
		<div
			className={`fa-branch-graph-node-shell ${
				isRouteThread || detailThreadId === node.thread_id ? "active-card" : ""
			}`}
			style={
				{
					left: `${graphNode.x}px`,
					top: `${graphNode.y}px`,
					"--fa-branch-role-color": roleColor(node.branch_role),
				} as CSSProperties
			}
		>
			<button
				aria-current={isRouteThread ? "page" : undefined}
				className={`fa-branch-graph-node-hit flex min-w-0 items-center gap-2 rounded-[var(--fa-radius-md)] border-0 bg-transparent p-0 text-left text-[color:var(--fa-text)] ${focusRing}`}
				onClick={() => onOpenThread(node.thread_id)}
				type="button"
			>
				<span
					aria-hidden="true"
					className={`fa-branch-graph-node shrink-0 ${isRouteThread ? "is-active" : ""} ${
						isFocused ? "is-focused" : ""
					} ${isContext ? "is-context" : ""} ${tone}`}
				/>
				<span className="grid min-w-0 gap-1">
					<span className="max-w-[150px] truncate text-[length:var(--fa-fs-sm)] font-semibold leading-[var(--fa-lh-tight)]">
						{node.branch_name}
					</span>
					<span className="flex items-center gap-1 whitespace-nowrap text-[length:var(--fa-fs-xs)] leading-[var(--fa-lh-tight)] text-[color:var(--fa-text-muted)]">
						<Badge tone={statusBadgeTone(node.branch_status)}>
							{branchStatusLabel(node.branch_status, isChineseUi)}
						</Badge>
						<span>{roleLabel(node.branch_role, isChineseUi)}</span>
						{isStale ? (
							<Badge
								tone="warning"
								{...tooltipProps(staleBranchTooltip(isChineseUi))}
							>
								{staleBranchLabel(isChineseUi)}
							</Badge>
						) : null}
					</span>
				</span>
			</button>
			<button
				aria-expanded={isDetailPinned}
				aria-haspopup="dialog"
				aria-label={detailsLabel}
				className={`fa-branch-graph-node-more grid h-6 w-6 shrink-0 place-items-center rounded-[var(--fa-radius-pill)] border border-transparent bg-transparent p-0 text-[color:var(--fa-text-muted)] hover:border-[color:var(--fa-border)] hover:text-[color:var(--fa-text)] ${focusRing}`}
				onClick={(event) => onToggleDetailPinned(node, event.currentTarget)}
				title={detailsLabel}
				type="button"
			>
				<svg aria-hidden="true" height="14" viewBox="0 0 20 20" width="14">
					<circle cx="4.5" cy="10" fill="currentColor" r="1.6" />
					<circle cx="10" cy="10" fill="currentColor" r="1.6" />
					<circle cx="15.5" cy="10" fill="currentColor" r="1.6" />
				</svg>
			</button>
		</div>
	);
}
