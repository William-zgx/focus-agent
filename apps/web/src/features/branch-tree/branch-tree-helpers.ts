import type { BranchTreeNode } from "@focus-agent/web-sdk";

export type BranchGraphNode = {
	node: BranchTreeNode;
	x: number;
	y: number;
};

type BranchGraphEdge = {
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

// One row per node (pre-order), indented by depth, so every node has room for
// a visible label to the right of its dot and edges stay in the indent gutter.
const NODE_X_START = 22;
const NODE_X_GAP = 30;
const NODE_Y_START = 58;
const NODE_Y_GAP = 54;
const NODE_LABEL_WIDTH = 210;
const GRAPH_NODE_SIZE = 24;
const GRAPH_NODE_RADIUS = GRAPH_NODE_SIZE / 2;
const GRAPH_EDGE_NODE_CLEARANCE = GRAPH_NODE_RADIUS + 1;
const GRAPH_EDGE_ELBOW_RADIUS = 10;
const BRANCH_STALE_AFTER_MS = 3 * 24 * 60 * 60 * 1000;

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

export function buildGraph(root?: BranchTreeNode | null): BranchGraph {
	if (!root) {
		return { nodes: [], edges: [], width: 220, height: 220 };
	}

	const nodes: BranchGraphNode[] = [];
	const edges: BranchGraphEdge[] = [];
	let maxDepth = 0;

	function walk(node: BranchTreeNode, depth: number, parent?: BranchTreeNode) {
		maxDepth = Math.max(maxDepth, depth);
		nodes.push({
			node,
			x: NODE_X_START + depth * NODE_X_GAP,
			y: NODE_Y_START + nodes.length * NODE_Y_GAP,
		});
		if (parent) {
			edges.push({
				from: parent.thread_id,
				to: node.thread_id,
				color: roleColor(node.branch_role),
			});
		}
		for (const child of node.children) {
			walk(child, depth + 1, node);
		}
	}

	walk(root, 0);

	const width = Math.max(
		260,
		NODE_X_START + maxDepth * NODE_X_GAP + GRAPH_NODE_RADIUS + NODE_LABEL_WIDTH,
	);
	const height = Math.max(
		220,
		NODE_Y_START + (nodes.length - 1) * NODE_Y_GAP + NODE_Y_START,
	);

	return { nodes, edges, width, height };
}

export function edgePath(from: BranchGraphNode, to: BranchGraphNode) {
	// Drop straight down from the parent's dot, then turn right into the child.
	const startX = from.x;
	const startY = from.y + GRAPH_EDGE_NODE_CLEARANCE;
	const endX = to.x - GRAPH_EDGE_NODE_CLEARANCE;
	const endY = to.y;
	const radius = Math.max(
		0,
		Math.min(GRAPH_EDGE_ELBOW_RADIUS, endY - startY, endX - startX),
	);
	return `M ${startX} ${startY} L ${startX} ${endY - radius} Q ${startX} ${endY} ${startX + radius} ${endY} L ${endX} ${endY}`;
}

export function branchActivityTime(node?: BranchTreeNode | null) {
	const timestamp = Date.parse(String(node?.last_activity_at ?? ""));
	return Number.isFinite(timestamp) ? timestamp : null;
}

export function isBranchStale(node: BranchTreeNode, now = Date.now()) {
	if (!node.branch_id || node.is_archived) return false;
	if (["merged", "discarded", "closed"].includes(node.branch_status)) {
		return false;
	}
	const activity = branchActivityTime(node);
	return activity !== null && now - activity > BRANCH_STALE_AFTER_MS;
}

export function staleBranchLabel(isChineseUi = false) {
	return isChineseUi ? "闲置" : "Stale";
}

export function staleBranchTooltip(isChineseUi = false) {
	return isChineseUi
		? "超过 3 天没有新进展，建议评审并合并结论，或归档这个分支。"
		: "No activity for over 3 days. Review & merge its conclusion, or archive it.";
}

export function branchActivityLabel(
	node: BranchTreeNode,
	isChineseUi = false,
	now = Date.now(),
) {
	const activity = branchActivityTime(node);
	if (activity === null) return "";
	const minutes = Math.round((activity - now) / 60_000);
	const formatter = new Intl.RelativeTimeFormat(isChineseUi ? "zh" : "en", {
		numeric: "auto",
		style: "short",
	});
	if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
	const hours = Math.round(minutes / 60);
	if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
	return formatter.format(Math.round(hours / 24), "day");
}

export function statusBadgeTone(status: BranchTreeNode["branch_status"]) {
	switch (statusAccentTone(status)) {
		case "is-success":
			return "success" as const;
		case "is-warn":
			return "warning" as const;
		case "is-danger":
			return "danger" as const;
		default:
			return status === "active" ? ("info" as const) : ("status" as const);
	}
}
