import type { BranchMeta, FocusAgentForkBrief } from "@focus-agent/web-sdk";
import { Link, useRouterState } from "@tanstack/react-router";
import { useId, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
	findNode,
	roleLabel,
} from "@/features/branch-tree/branch-tree-helpers";
import { useBranchTree } from "@/features/branch-tree/use-branch-tree";
import { useThreadState } from "@/features/thread/use-thread-state";

const TURN_PREVIEW_LIMIT = 280;

const sectionLabelClass =
	"text-[length:var(--fa-fs-xs)] font-semibold text-[color:var(--fa-text-soft)]";
const bodyTextClass =
	"m-0 whitespace-pre-wrap break-words text-[length:var(--fa-fs-sm)] leading-[var(--fa-lh-normal)] text-[color:var(--fa-text)]";
const focusRing =
	"focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fa-focus-ring)]";

function clip(text: string, limit: number) {
	const trimmed = text.trim();
	return trimmed.length > limit
		? `${trimmed.slice(0, limit).trimEnd()}…`
		: trimmed;
}

function formatForkedAt(value: string, isChineseUi: boolean) {
	const timestamp = Date.parse(value);
	if (!Number.isFinite(timestamp)) return "";
	return new Intl.DateTimeFormat(isChineseUi ? "zh-CN" : "en", {
		dateStyle: "medium",
		timeStyle: "short",
	}).format(timestamp);
}

function readForkBrief(meta: BranchMeta): FocusAgentForkBrief | null {
	const brief = meta.fork_brief;
	if (!brief || typeof brief !== "object") return null;
	return {
		goal: String(brief.goal ?? ""),
		parent_summary: String(brief.parent_summary ?? ""),
		parent_recent_turns: Array.isArray(brief.parent_recent_turns)
			? brief.parent_recent_turns.filter(
					(turn) => turn && typeof turn.content === "string",
				)
			: [],
		forked_at: String(brief.forked_at ?? ""),
		parent_message_count: Number(brief.parent_message_count) || 0,
	};
}

/**
 * Collapsible "Branch brief" strip under the chat header: what this branch set
 * out to do and what it inherited from its parent at fork time.
 */
export function ThreadBranchBrief() {
	const { conversationId, threadId } = useRouterState({
		select: (state) => {
			const lastMatch = state.matches[state.matches.length - 1];
			const params = (lastMatch?.params ?? {}) as Partial<
				Record<"conversationId" | "threadId", string>
			>;
			return {
				conversationId: String(params.conversationId ?? ""),
				threadId: String(params.threadId ?? ""),
			};
		},
	});
	const { isChineseUi } = useShellUi();
	const { data } = useThreadState(threadId);
	const { data: tree } = useBranchTree(threadId);
	const [expanded, setExpanded] = useState(false);
	const panelId = useId();
	const meta = data?.branch_meta;

	if (!meta?.branch_id || !meta.parent_thread_id) return null;

	const rootThreadId = data?.root_thread_id || conversationId;
	const brief = readForkBrief(meta);
	const parentName =
		findNode(tree?.root, meta.parent_thread_id)?.branch_name ||
		(meta.parent_thread_id === rootThreadId
			? isChineseUi
				? "主线"
				: "Main"
			: meta.parent_thread_id);
	const role = roleLabel(meta.branch_role, isChineseUi);
	const forkedAt = brief ? formatForkedAt(brief.forked_at, isChineseUi) : "";
	const summaryLine = brief?.goal
		? brief.goal
		: isChineseUi
			? `${meta.branch_name}（${role}）`
			: `${meta.branch_name} (${role})`;

	const parentLink = (
		<Link
			className={`font-semibold text-[color:var(--fa-accent-text-strong)] underline underline-offset-2 ${focusRing}`}
			params={{ conversationId: rootThreadId, threadId: meta.parent_thread_id }}
			to="/c/$conversationId/t/$threadId"
		>
			{parentName}
		</Link>
	);

	return (
		<section
			aria-label={isChineseUi ? "分支简报" : "Branch brief"}
			className="mt-3 border-t border-[color:var(--fa-border-subtle)] pt-2"
		>
			<button
				aria-controls={panelId}
				aria-expanded={expanded}
				className={`flex w-full min-w-0 items-center gap-2 rounded-[var(--fa-radius-sm)] border-0 bg-transparent px-1 py-1 text-left text-[length:var(--fa-fs-sm)] text-[color:var(--fa-text-muted)] hover:text-[color:var(--fa-text)] ${focusRing}`}
				onClick={() => setExpanded((value) => !value)}
				type="button"
			>
				<svg
					aria-hidden="true"
					className={`shrink-0 transition-transform duration-[var(--fa-dur-fast)] ${expanded ? "rotate-90" : ""}`}
					height="12"
					viewBox="0 0 12 12"
					width="12"
				>
					<path
						d="M4 2.5 7.5 6 4 9.5"
						fill="none"
						stroke="currentColor"
						strokeLinecap="round"
						strokeWidth="1.6"
					/>
				</svg>
				<span className="shrink-0 font-semibold text-[color:var(--fa-text)]">
					{isChineseUi ? "分支简报" : "Branch brief"}
				</span>
				<span className="min-w-0 truncate">{summaryLine}</span>
			</button>

			{expanded ? (
				<div
					className="mt-2 grid max-h-[40vh] gap-3 overflow-auto px-1 pb-1"
					id={panelId}
				>
					{brief?.goal ? (
						<div className="grid gap-1">
							<span className={sectionLabelClass}>
								{isChineseUi ? "目标" : "Goal"}
							</span>
							<p className={bodyTextClass}>{brief.goal}</p>
						</div>
					) : null}

					{brief?.parent_summary ? (
						<div className="grid gap-1">
							<span className={sectionLabelClass}>
								{isChineseUi ? "分叉时的上游摘要" : "Parent summary at fork"}
							</span>
							<p className={bodyTextClass}>{brief.parent_summary}</p>
						</div>
					) : null}

					{brief && brief.parent_recent_turns.length > 0 ? (
						<div className="grid gap-1">
							<span className={sectionLabelClass}>
								{isChineseUi ? "上游最近对话" : "Recent parent turns"}
							</span>
							<ol className="m-0 grid list-none gap-2 p-0">
								{brief.parent_recent_turns.map((turn, index) => (
									<li
										className="grid gap-0.5 border-l-2 border-[color:var(--fa-border)] pl-2"
										// biome-ignore lint/suspicious/noArrayIndexKey: fork-time snapshot never reorders
										key={index}
									>
										<span className={sectionLabelClass}>
											{turn.role === "user"
												? isChineseUi
													? "你"
													: "You"
												: "Focus Agent"}
										</span>
										<p className={bodyTextClass}>
											{clip(turn.content, TURN_PREVIEW_LIMIT)}
										</p>
									</li>
								))}
							</ol>
						</div>
					) : null}

					<dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-[length:var(--fa-fs-sm)]">
						<dt className={sectionLabelClass}>
							{isChineseUi ? "上游分支" : "Parent"}
						</dt>
						<dd className="m-0 min-w-0 truncate">{parentLink}</dd>
						<dt className={sectionLabelClass}>
							{isChineseUi ? "分支" : "Branch"}
						</dt>
						<dd className="m-0 min-w-0 truncate text-[color:var(--fa-text)]">
							{meta.branch_name} · {role}
						</dd>
						{forkedAt ? (
							<>
								<dt className={sectionLabelClass}>
									{isChineseUi ? "分叉时间" : "Forked"}
								</dt>
								<dd className="m-0 text-[color:var(--fa-text)]">
									{forkedAt}
									{brief?.parent_message_count
										? isChineseUi
											? `（上游当时 ${brief.parent_message_count} 条消息）`
											: ` (parent had ${brief.parent_message_count} messages)`
										: ""}
								</dd>
							</>
						) : null}
					</dl>

					{!brief ? (
						<p className="m-0 text-[length:var(--fa-fs-xs)] text-[color:var(--fa-text-soft)]">
							{isChineseUi
								? "这个分支创建于分支简报功能之前，没有记录分叉时的目标与上下文。"
								: "This branch predates branch briefs, so its fork-time goal and context weren't recorded."}
						</p>
					) : null}
				</div>
			) : null}
		</section>
	);
}
