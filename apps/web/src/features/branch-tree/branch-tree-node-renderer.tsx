import type { BranchTreeNode } from "@focus-agent/web-sdk";
import type { CSSProperties, RefObject } from "react";

import type { BranchGraphNode } from "@/features/branch-tree/branch-tree-helpers";
import {
	branchStatusLabel,
	roleColor,
	roleLabel,
	statusTone,
} from "@/features/branch-tree/branch-tree-helpers";

type BranchTreeNodeRendererProps = {
	detailOverlayRef: RefObject<HTMLDivElement | null>;
	detailThreadId: string;
	graphNode: BranchGraphNode;
	isChineseUi: boolean;
	isContext: boolean;
	isFocused: boolean;
	isRouteThread: boolean;
	onOpenThread: (threadId: string) => void;
	onRequestDetail: (
		node: BranchTreeNode,
		anchorElement: HTMLElement | null,
	) => void;
	onRequestHideDetail: () => void;
};

export function BranchTreeNodeRenderer({
	detailOverlayRef,
	detailThreadId,
	graphNode,
	isChineseUi,
	isContext,
	isFocused,
	isRouteThread,
	onOpenThread,
	onRequestDetail,
	onRequestHideDetail,
}: BranchTreeNodeRendererProps) {
	const node = graphNode.node;
	const tone = statusTone(node.branch_status);

	function shouldKeepDetailOpen(relatedTarget: EventTarget | null) {
		return (
			relatedTarget instanceof Node &&
			detailOverlayRef.current?.contains(relatedTarget)
		);
	}

	return (
		<div
			className={`fa-branch-graph-node-shell ${
				isRouteThread || detailThreadId === node.thread_id ? "active-card" : ""
			}`}
			style={{ left: `${graphNode.x}px`, top: `${graphNode.y}px` }}
		>
			<button
				className={`fa-branch-graph-node ${isRouteThread ? "is-active" : ""} ${
					isFocused ? "is-focused" : ""
				} ${isContext ? "is-context" : ""} ${tone}`}
				style={
					{
						"--fa-branch-role-color": roleColor(node.branch_role),
					} as CSSProperties
				}
				onClick={() => onOpenThread(node.thread_id)}
				onFocus={(event) => onRequestDetail(node, event.currentTarget)}
				onMouseEnter={(event) => onRequestDetail(node, event.currentTarget)}
				onMouseLeave={(event) => {
					if (shouldKeepDetailOpen(event.relatedTarget)) {
						return;
					}
					onRequestHideDetail();
				}}
				onBlur={(event) => {
					if (shouldKeepDetailOpen(event.relatedTarget)) {
						return;
					}
					onRequestHideDetail();
				}}
				type="button"
			>
				<span className="sr-only">
					{node.branch_name} · {roleLabel(node.branch_role, isChineseUi)} ·{" "}
					{branchStatusLabel(node.branch_status, isChineseUi)}
				</span>
			</button>
		</div>
	);
}
