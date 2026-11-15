import type {
	FocusAgentAttentionItem,
	FocusAgentAttentionSnapshot,
} from "@focus-agent/web-sdk";
import { FocusAgentRequestError } from "@focus-agent/web-sdk";
import { memo, useRef, useState } from "react";
import type { ThreadLinks } from "@/entities/messages/message-branch-import-card";
import { branchActionCardDomId } from "@/entities/messages/message-list-branch-action-card";
import { Badge, Button } from "@/shared/ui/primitives";

import { useThreadAttention } from "./use-thread-attention";

export type AttentionView = "focus" | "audit";

interface ThreadAttentionPanelProps {
	threadId: string;
	isChineseUi: boolean;
	attentionView: AttentionView;
	onAttentionViewChange: (view: AttentionView) => void;
	threadLinks?: ThreadLinks;
}

const ATTENTION_KIND_LABELS: Record<string, [string, string]> = {
	branch_action: ["分支操作", "Branch action"],
	branch_handoff: ["分支接管", "Branch handoff"],
	merge_decision: ["合并决定", "Merge decision"],
	proposal: ["合并提案", "Merge proposal"],
	merge_proposal: ["合并提案", "Merge proposal"],
	interrupt: ["等待回答", "Input needed"],
	tool_outcome: ["工具结果", "Tool result"],
	message: ["新回复", "New reply"],
	task_outcome: ["运行结果", "Run outcome"],
	thread: ["当前线程", "Thread"],
	run: ["运行记录", "Run"],
};

function hasDiff(snapshot: FocusAgentAttentionSnapshot) {
	return Boolean(
		snapshot.diff.frontier_missing ||
			snapshot.diff.new_message_count ||
			snapshot.diff.new_outcome_count ||
			snapshot.diff.action_transition_count ||
			snapshot.diff.highlights.length,
	);
}

function itemKindLabel(kind: string, isChineseUi: boolean) {
	const label = ATTENTION_KIND_LABELS[kind];
	if (label) return label[isChineseUi ? 0 : 1];
	return isChineseUi ? "相关记录" : kind.replaceAll("_", " ");
}

function attentionPolicyLabel(
	level: FocusAgentAttentionSnapshot["policy"]["level"],
	isChineseUi: boolean,
) {
	if (level === "ask")
		return isChineseUi ? "需要你处理" : "Needs your decision";
	if (level === "notify") return isChineseUi ? "建议检查" : "Review suggested";
	return isChineseUi ? "恢复上下文" : "Resume context";
}

function AttentionItems({
	items,
	isChineseUi,
}: {
	items: FocusAgentAttentionItem[];
	isChineseUi: boolean;
}) {
	return (
		<ul className="fa-attention-items">
			{items.map((item) => (
				<li key={`${item.kind}:${item.source_id}:${item.status}`}>
					<span className="fa-attention-item-kind">
						{itemKindLabel(item.kind, isChineseUi)}
					</span>
					<span>{item.text}</span>
				</li>
			))}
		</ul>
	);
}

function ThreadAttentionPanelComponent({
	threadId,
	isChineseUi,
	attentionView,
	onAttentionViewChange,
	threadLinks,
}: ThreadAttentionPanelProps) {
	const {
		data,
		error,
		isLoading,
		refetch,
		markReviewed,
		reviewError,
		isReviewing,
	} = useThreadAttention(threadId);
	const [openOverride, setOpenOverride] = useState<boolean | null>(null);
	const [dismissedRevision, setDismissedRevision] = useState<string | null>(
		null,
	);

	const changed = data ? hasDiff(data) : false;
	const initialDiffRef = useRef<boolean | null>(null);
	if (data && initialDiffRef.current === null) {
		initialDiffRef.current = changed;
	}
	const hasResumeValue = Boolean(
		data &&
			(data.resume.goal ||
				data.resume.decisions.length ||
				data.resume.open_items.length ||
				data.resume.next_action),
	);
	const shouldDisplay = Boolean(
		data && (data.policy.level !== "quiet" || changed || hasResumeValue),
	);
	const defaultOpen = Boolean(
		data &&
			shouldDisplay &&
			(data.policy.level !== "quiet" ||
				(initialDiffRef.current && changed) ||
				data.resume.decisions.length ||
				data.resume.open_items.length),
	);
	const shouldForceOpen =
		data?.diff.frontier_missing ||
		data?.diff.new_failed_outcome_count ||
		data?.diff.action_transition_count ||
		data?.policy.level !== "quiet";
	const attentionRevision = data
		? [
				data.policy.level,
				data.diff.new_failed_outcome_count,
				data.diff.action_transition_count,
				data.diff.frontier_missing,
				...data.resume.open_items.map(
					(item) => `${item.kind}:${item.source_id}`,
				),
			].join(":")
		: "";
	let isOpen = openOverride ?? defaultOpen;
	if (
		openOverride === false &&
		shouldForceOpen &&
		attentionRevision !== dismissedRevision
	) {
		isOpen = true;
	}
	const setOpen = (open: boolean) => {
		if (!open) setDismissedRevision(attentionRevision);
		setOpenOverride(open);
	};
	const remainingOpenItems = (data?.resume.open_items ?? []).filter(
		(item) =>
			!data?.resume.next_action ||
			item.kind !== data.resume.next_action.kind ||
			item.source_id !== data.resume.next_action.source_id ||
			item.status !== data.resume.next_action.status,
	);
	const visibleEvidence = (data?.resume.evidence ?? []).filter(
		(evidence) => evidence.thread_id !== threadId || evidence.action_id,
	);
	const diffMetrics = data
		? [
				data.diff.new_message_count
					? isChineseUi
						? `${data.diff.new_message_count} 条新消息`
						: `${data.diff.new_message_count} new messages`
					: "",
				data.diff.new_outcome_count
					? isChineseUi
						? `${data.diff.new_outcome_count} 个工具结果`
						: `${data.diff.new_outcome_count} tool outcomes`
					: "",
				data.diff.new_failed_outcome_count
					? isChineseUi
						? `${data.diff.new_failed_outcome_count} 个失败`
						: `${data.diff.new_failed_outcome_count} failed`
					: "",
				data.diff.action_transition_count
					? isChineseUi
						? `${data.diff.action_transition_count} 个状态变化`
						: `${data.diff.action_transition_count} status changes`
					: "",
			].filter(Boolean)
		: [];

	const viewToggle = (
		<Button
			className="fa-attention-view-toggle"
			onClick={() =>
				onAttentionViewChange(attentionView === "focus" ? "audit" : "focus")
			}
			size="sm"
			type="button"
			variant="ghost"
		>
			{attentionView === "focus"
				? isChineseUi
					? "显示全部诊断"
					: "Show all diagnostics"
				: isChineseUi
					? "低打扰视图"
					: "Focus view"}
		</Button>
	);

	if (isLoading || !data) {
		const unsupported =
			error instanceof FocusAgentRequestError && error.status === 404;
		return (
			<div className="fa-attention-workbench">
				{error && !unsupported ? (
					<div className="fa-attention-load-error">
						<span>
							{isChineseUi
								? "恢复信息加载失败。"
								: "Could not load resume context."}
						</span>
						<Button onClick={() => void refetch()} size="sm" variant="ghost">
							{isChineseUi ? "重试" : "Retry"}
						</Button>
					</div>
				) : null}
				{viewToggle}
			</div>
		);
	}

	if (!isOpen) {
		return (
			<div className="fa-attention-workbench">
				{shouldDisplay ? (
					<Button
						className="fa-attention-resume-trigger"
						onClick={() => setOpen(true)}
						size="sm"
						type="button"
						variant="ghost"
					>
						{attentionPolicyLabel(data.policy.level, isChineseUi)}
						{changed || data.policy.level !== "quiet" ? (
							<>
								<span className="fa-attention-unread" />
								<span className="sr-only">
									{isChineseUi ? "有变化" : "Changes"}
								</span>
							</>
						) : null}
					</Button>
				) : null}
				{viewToggle}
			</div>
		);
	}

	return (
		<section
			aria-label={isChineseUi ? "恢复上下文" : "Resume context"}
			aria-live={data.policy.level === "ask" ? "polite" : "off"}
			className={`fa-attention-panel is-${data.policy.level}`}
		>
			<header className="fa-attention-panel-header">
				<div>
					<strong>{isChineseUi ? "从这里继续" : "Pick up here"}</strong>
					<span className="fa-attention-policy-label">
						{attentionPolicyLabel(data.policy.level, isChineseUi)}
					</span>
				</div>
				<div className="fa-attention-header-actions">
					{viewToggle}
					<Button
						onClick={() => setOpen(false)}
						size="sm"
						type="button"
						variant="ghost"
					>
						{isChineseUi ? "收起" : "Collapse"}
					</Button>
				</div>
			</header>

			{data.resume.goal ? (
				<div className="fa-attention-goal">
					<span>{isChineseUi ? "目标" : "Goal"}</span>
					<p>{data.resume.goal}</p>
				</div>
			) : null}

			{data.diff.frontier_missing ? (
				<p className="fa-attention-notice">
					{isChineseUi
						? "较早的已读位置已不可用；请从原始消息核对历史。"
						: "Your earlier review point is unavailable. Verify history in the transcript."}
				</p>
			) : null}

			{diffMetrics.length ? (
				<section
					className="fa-attention-diff-metrics"
					aria-label={
						isChineseUi ? "离开后的变化" : "Changes since your last visit"
					}
				>
					{diffMetrics.map((metric) => (
						<Badge key={metric} tone="status">
							{metric}
						</Badge>
					))}
				</section>
			) : null}

			{data.resume.next_action ? (
				<div className="fa-attention-next-action">
					<span>{isChineseUi ? "下一步" : "Next action"}</span>
					<strong>{data.resume.next_action.text}</strong>
				</div>
			) : null}

			{remainingOpenItems.length ? (
				<div className="fa-attention-section">
					<h2>{isChineseUi ? "其他待处理" : "Other open items"}</h2>
					<AttentionItems
						isChineseUi={isChineseUi}
						items={remainingOpenItems}
					/>
				</div>
			) : null}

			{data.diff.highlights.length ? (
				<div className="fa-attention-section">
					<h2>{isChineseUi ? "离开后的进展" : "While you were away"}</h2>
					<AttentionItems
						isChineseUi={isChineseUi}
						items={data.diff.highlights}
					/>
				</div>
			) : null}

			{data.resume.decisions.length ? (
				<div className="fa-attention-section">
					<h2>{isChineseUi ? "已决定" : "Already decided"}</h2>
					<AttentionItems
						isChineseUi={isChineseUi}
						items={data.resume.decisions}
					/>
				</div>
			) : null}

			{visibleEvidence.length > 0 && threadLinks ? (
				<div className="fa-attention-evidence">
					{visibleEvidence.map((evidence) => (
						<Button
							key={`${evidence.kind}:${evidence.source_id}`}
							onClick={() => {
								if (evidence.thread_id !== threadId) {
									threadLinks.open(evidence.thread_id);
									return;
								}
								setOpen(false);
								window.requestAnimationFrame(() => {
									const target = document.getElementById(
										branchActionCardDomId(evidence.action_id ?? ""),
									);
									if (target instanceof HTMLDetailsElement) {
										target.open = true;
										target.focus({ preventScroll: true });
									}
									(
										target ?? document.querySelector(".fa-chat-history")
									)?.scrollIntoView({ block: "center" });
								});
							}}
							size="sm"
							type="button"
							variant="ghost"
						>
							{isChineseUi ? "查看" : "Open"}{" "}
							{itemKindLabel(evidence.kind, isChineseUi)}
						</Button>
					))}
				</div>
			) : null}

			{reviewError ? (
				<p className="fa-attention-notice is-danger" role="alert">
					{isChineseUi
						? "标记已读失败，请重试。"
						: "Could not mark this context as reviewed. Try again."}
				</p>
			) : null}

			<footer className="fa-attention-panel-footer">
				<Button
					disabled={isReviewing}
					onClick={async () => {
						try {
							await markReviewed(data.current_cursor);
							setOpen(false);
						} catch {
							// The mutation exposes the error while keeping the snapshot visible.
						}
					}}
					size="sm"
					type="button"
					variant="secondary"
				>
					{isReviewing
						? isChineseUi
							? "保存中…"
							: "Saving…"
						: isChineseUi
							? "标记已读"
							: "Mark reviewed"}
				</Button>
			</footer>
		</section>
	);
}

export const ThreadAttentionPanel = memo(ThreadAttentionPanelComponent);
