import type { BranchTreeNode } from "@focus-agent/web-sdk";
import type { CSSProperties, RefObject } from "react";

import { BranchTreeNodeRenderer } from "@/features/branch-tree/branch-tree-node-renderer";
import type {
	BranchGraph,
	BranchGraphNode,
} from "@/features/branch-tree/branch-tree-helpers";
import {
	edgePath,
	roleColor,
} from "@/features/branch-tree/branch-tree-helpers";

type BranchTreeGraphCanvasProps = {
	branchZoom: number;
	detailOverlayRef: RefObject<HTMLDivElement | null>;
	detailThreadId: string;
	graph: BranchGraph;
	graphShellRef: RefObject<HTMLDivElement | null>;
	isChineseUi: boolean;
	isLoading: boolean;
	nodeIndex: Map<string, BranchGraphNode>;
	onOpenThread: (threadId: string) => void;
	onRequestDetail: (
		node: BranchTreeNode,
		anchorElement: HTMLElement | null,
	) => void;
	onRequestHideDetail: () => void;
	previewNode: BranchTreeNode | null;
	previewThreadId: string;
	root: BranchTreeNode | null | undefined;
	routeThreadId: string;
	selectedThreadId: string;
	treeCanvasRef: RefObject<HTMLDivElement | null>;
	viewportNudge: { x: number; y: number };
};

export function BranchTreeGraphCanvas({
	branchZoom,
	detailOverlayRef,
	detailThreadId,
	graph,
	graphShellRef,
	isChineseUi,
	isLoading,
	nodeIndex,
	onOpenThread,
	onRequestDetail,
	onRequestHideDetail,
	previewNode,
	previewThreadId,
	root,
	routeThreadId,
	selectedThreadId,
	treeCanvasRef,
	viewportNudge,
}: BranchTreeGraphCanvasProps) {
	return (
		<div ref={treeCanvasRef} className="fa-tree-canvas">
			{isLoading ? (
				<div className="fa-inline-notice">
					{isChineseUi ? "正在加载分支树..." : "Loading branch tree..."}
				</div>
			) : null}
			{!isLoading && !root ? (
				<div className="fa-inline-notice">
					{isChineseUi
						? "先打开一个对话，再加载对应分支树。"
						: "Open a conversation to load its branch tree."}
				</div>
			) : null}

			{root ? (
				<div className="fa-tree-canvas-content">
					<div
						ref={graphShellRef}
						className="fa-branch-graph-shell"
						style={{
							width: `${graph.width * branchZoom}px`,
							height: `${graph.height * branchZoom}px`,
							transform: `translate(${viewportNudge.x}px, ${viewportNudge.y}px)`,
						}}
					>
						<div
							className={`fa-branch-graph-main ${selectedThreadId ? "has-active-selection" : ""}`}
							style={{
								width: `${graph.width}px`,
								height: `${graph.height}px`,
								transform: `scale(${branchZoom})`,
							}}
						>
							<div
								className="fa-branch-graph-root-label"
								style={
									{
										"--fa-branch-role-color": roleColor(root.branch_role),
									} as CSSProperties
								}
							>
								{isChineseUi ? "主线时间轴" : "Main timeline"}
							</div>
							<svg
								className="fa-branch-graph-lines"
								width={graph.width}
								height={graph.height}
								viewBox={`0 0 ${graph.width} ${graph.height}`}
								aria-hidden="true"
							>
								{graph.edges.map((edge) => {
									const from = nodeIndex.get(edge.from);
									const to = nodeIndex.get(edge.to);
									if (!from || !to) return null;
									const isContext =
										edge.from === previewThreadId ||
										edge.to === previewThreadId ||
										previewNode?.parent_thread_id === edge.from;
									const isFocused =
										edge.from === selectedThreadId ||
										edge.to === selectedThreadId;
									return (
										<path
											key={`${edge.from}-${edge.to}`}
											className={`fa-branch-graph-edge ${isContext ? "is-context" : ""} ${
												isFocused ? "is-focused" : ""
											}`}
											d={edgePath(from, to)}
											stroke={edge.color}
										/>
									);
								})}
							</svg>

							{graph.nodes.map((item) => {
								const node = item.node;
								const isContext =
									node.thread_id === previewThreadId ||
									node.parent_thread_id === previewThreadId ||
									previewNode?.parent_thread_id === node.thread_id;
								return (
									<BranchTreeNodeRenderer
										key={node.thread_id}
										detailOverlayRef={detailOverlayRef}
										detailThreadId={detailThreadId}
										graphNode={item}
										isChineseUi={isChineseUi}
										isContext={isContext}
										isFocused={node.thread_id === selectedThreadId}
										isRouteThread={node.thread_id === routeThreadId}
										onOpenThread={onOpenThread}
										onRequestDetail={onRequestDetail}
										onRequestHideDetail={onRequestHideDetail}
									/>
								);
							})}
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}
