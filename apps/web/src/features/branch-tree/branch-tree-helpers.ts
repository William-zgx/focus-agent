import type { BranchTreeNode } from "@focus-agent/web-sdk";

export type BranchGraphNode = {
	node: BranchTreeNode;
	x: number;
	y: number;
};

export type BranchGraphEdge = {
	from: string;
	to: string;
	color: string;
};

export type BranchGraph = {
	nodes: BranchGraphNode[];
	edges: BranchGraphEdge[];
	width: number;
	height: number;
};

const NODE_X_START = 42;
const NODE_X_GAP = 108;
const NODE_Y_START = 48;
const NODE_Y_GAP = 76;
const GRAPH_NODE_SIZE = 24;
const GRAPH_NODE_RADIUS = GRAPH_NODE_SIZE / 2;
const GRAPH_EDGE_NODE_CLEARANCE = GRAPH_NODE_RADIUS + 1;
const GRAPH_FOCUS_TARGET_Y = 184;
const GRAPH_TOP_PADDING = 34;

export const BRANCH_DETAIL_WIDTH = 228;
export const BRANCH_DETAIL_HEIGHT_ESTIMATE = 260;
export const BRANCH_DETAIL_HIDE_DELAY_MS = 120;
export const BRANCH_ZOOM_STEP = 0.1;

export function roleLabel(
	role: BranchTreeNode["branch_role"],
	isChineseUi = false,
) {
	switch (role) {
		case "deep_dive":
			return isChineseUi ? "深挖" : "Deep dive";
		case "execute":
			return isChineseUi ? "执行" : "Execute";
		case "explore_alternatives":
			return isChineseUi ? "探索" : "Explore";
		case "verify":
			return isChineseUi ? "验证" : "Verify";
		case "writeup":
			return isChineseUi ? "写作" : "Writeup";
		default:
			return isChineseUi ? "主线" : "Main";
	}
}

export function roleColor(role: BranchTreeNode["branch_role"]) {
	switch (role) {
		case "main":
			return "#6BA9FF";
		case "explore_alternatives":
			return "#5EC2FF";
		case "deep_dive":
			return "#A78BFA";
		case "execute":
			return "#FB7185";
		case "verify":
			return "#F59E0B";
		case "writeup":
			return "#34D399";
		default:
			return "#5EC2FF";
	}
}

export function statusTone(status: BranchTreeNode["branch_status"]) {
	switch (status) {
		case "preparing_merge_review":
			return "is-pending";
		case "awaiting_merge_review":
			return "is-ready";
		case "paused":
			return "is-paused";
		case "merged":
			return "is-merged";
		case "discarded":
		case "closed":
			return "is-merged";
		default:
			return "";
	}
}

export function statusAccentTone(status: BranchTreeNode["branch_status"]) {
	switch (status) {
		case "awaiting_merge_review":
			return "is-success";
		case "preparing_merge_review":
		case "paused":
			return "is-warn";
		case "merged":
			return "is-danger";
		default:
			return "";
	}
}

export function findNode(
	root: BranchTreeNode | undefined,
	threadId: string | undefined,
): BranchTreeNode | undefined {
	if (!root || !threadId) return undefined;
	if (root.thread_id === threadId) return root;
	for (const child of root.children) {
		const hit = findNode(child, threadId);
		if (hit) return hit;
	}
	return undefined;
}

export function countNodes(node?: BranchTreeNode | null): number {
	if (!node) return 0;
	return 1 + node.children.reduce((sum, child) => sum + countNodes(child), 0);
}

export function branchStatusLabel(
	status: BranchTreeNode["branch_status"],
	isChineseUi = false,
) {
	if (status === "awaiting_merge_review")
		return isChineseUi ? "等待评审" : "Awaiting review";
	if (status === "preparing_merge_review")
		return isChineseUi ? "准备评审" : "Preparing review";
	if (isChineseUi) {
		const labels: Record<string, string> = {
			active: "进行中",
			paused: "已暂停",
			merged: "已合并",
			discarded: "已丢弃",
			closed: "已关闭",
		};
		return labels[status] || status;
	}
	return status.replaceAll("_", " ");
}

export function shouldShowArchivedSecondaryLine(
	primary: string | undefined,
	secondary: string | undefined,
) {
	const normalizedPrimary = String(primary ?? "").trim();
	const normalizedSecondary = String(secondary ?? "").trim();
	return (
		Boolean(normalizedSecondary) && normalizedPrimary !== normalizedSecondary
	);
}

export function mergedBranchForkDisabledLabel(isChineseUi = false) {
	return isChineseUi
		? "已合并分支不能新建分支"
		: "Merged branches cannot create new branches";
}

export function formatTokenCount(value: number) {
	const normalized = Math.max(0, Number(value) || 0);
	if (normalized >= 1_000_000) {
		const millions = normalized / 1_000_000;
		return `${millions >= 10 ? millions.toFixed(0) : millions.toFixed(1).replace(/\.0$/, "")}M`;
	}
	if (normalized >= 1_000) {
		const thousands = normalized / 1_000;
		return `${thousands >= 10 ? thousands.toFixed(0) : thousands.toFixed(1).replace(/\.0$/, "")}K`;
	}
	return new Intl.NumberFormat("en-US").format(Math.round(normalized));
}

export function branchTotalTokens(node?: BranchTreeNode | null) {
	const raw = Number(node?.token_usage?.total_tokens ?? 0);
	return Number.isFinite(raw) ? Math.max(0, Math.round(raw)) : 0;
}

export function branchTokenUsageLabel(node?: BranchTreeNode | null) {
	return `${formatTokenCount(branchTotalTokens(node))} tokens`;
}

export function buildGraph(
	root?: BranchTreeNode | null,
	focusThreadId?: string,
): BranchGraph {
	if (!root) {
		return { nodes: [], edges: [], width: 220, height: 220 };
	}

	const nodes: BranchGraphNode[] = [];
	const edges: BranchGraphEdge[] = [];
	let cursorY = NODE_Y_START;
	let maxDepth = 0;

	function walk(
		node: BranchTreeNode,
		depth: number,
		parent?: BranchTreeNode,
	): number {
		maxDepth = Math.max(maxDepth, depth);
		const childCenters: number[] = [];
		for (const child of node.children) {
			childCenters.push(walk(child, depth + 1, node));
		}

		const y =
			childCenters.length > 0
				? (childCenters[0] + childCenters[childCenters.length - 1]) / 2
				: (() => {
						const next = cursorY;
						cursorY += NODE_Y_GAP;
						return next;
					})();
		const x = NODE_X_START + depth * NODE_X_GAP;

		nodes.push({ node, x, y });
		if (parent) {
			edges.push({
				from: parent.thread_id,
				to: node.thread_id,
				color: roleColor(node.branch_role),
			});
		}
		return y;
	}

	walk(root, 0);

	const minY = Math.min(...nodes.map((item) => item.y), NODE_Y_START);
	const focusNode = focusThreadId
		? nodes.find((item) => item.node.thread_id === focusThreadId)
		: undefined;
	const requestedShift = focusNode ? GRAPH_FOCUS_TARGET_Y - focusNode.y : 0;
	const minShift = GRAPH_TOP_PADDING - minY;
	const verticalShift = Math.max(minShift, requestedShift);
	const shiftedNodes =
		verticalShift === 0
			? nodes
			: nodes.map((item) => ({
					...item,
					y: item.y + verticalShift,
				}));
	const shiftedMaxY = Math.max(
		...shiftedNodes.map((item) => item.y),
		NODE_Y_START,
	);
	const width = Math.max(240, NODE_X_START * 2 + maxDepth * NODE_X_GAP + 56);
	const height = Math.max(220, shiftedMaxY + NODE_Y_START);

	return { nodes: shiftedNodes, edges, width, height };
}

export function edgePath(from: BranchGraphNode, to: BranchGraphNode) {
	const startX = from.x;
	const startY = from.y + GRAPH_EDGE_NODE_CLEARANCE;
	const endX = to.x;
	const endY = to.y - GRAPH_EDGE_NODE_CLEARANCE;
	const offsetY = Math.max(24, Math.min(48, (endY - startY) * 0.35));
	const offsetX = Math.max(28, Math.abs(endX - startX) * 0.4);
	return `M ${startX} ${startY} C ${startX + offsetX} ${startY + offsetY}, ${endX - offsetX} ${endY - offsetY}, ${endX} ${endY}`;
}
