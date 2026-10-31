import type { MouseEvent, ReactNode } from "react";
import { forwardRef } from "react";

import type { BranchImportView } from "./message-branch-import";
import { MessageMarkdown } from "./message-markdown";

export type ThreadLinks = {
	href: (threadId: string) => string;
	open: (threadId: string) => void;
};

type BranchImportCardProps = {
	id?: string;
	isChineseUi: boolean;
	isHighlighted?: boolean;
	threadLinks?: ThreadLinks | null;
	/** "preview" renders the merge-review preview (no link, softer chrome). */
	variant?: "transcript" | "preview";
	view: BranchImportView;
};

const sectionLabelClass =
	"m-0 text-[length:var(--fa-fs-xs)] font-semibold text-[color:var(--fa-text-soft)]";
const listClass =
	"m-0 grid gap-1 pl-5 text-[length:var(--fa-fs-sm)] leading-[var(--fa-lh-normal)]";
const linkClass =
	"break-all text-[color:var(--fa-accent-text-strong)] underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fa-focus-ring)]";

function isUrl(value: string) {
	return /^https?:\/\/\S+$/i.test(value.trim());
}

function ImportList({
	items,
	label,
	renderItem = (item) => item,
}: {
	items: string[];
	label: string;
	renderItem?: (item: string) => ReactNode;
}) {
	if (items.length === 0) return null;
	return (
		<div className="grid gap-1">
			<h4 className={sectionLabelClass}>{label}</h4>
			<ul className={listClass}>
				{items.map((item) => (
					<li key={item}>{renderItem(item)}</li>
				))}
			</ul>
		</div>
	);
}

export const BranchImportCard = forwardRef<HTMLElement, BranchImportCardProps>(
	function BranchImportCard(
		{ id, isChineseUi, isHighlighted = false, threadLinks, variant, view },
		ref,
	) {
		const title = view.branchName
			? `${isChineseUi ? "已合并分支结论" : "Merged branch conclusion"} · ${view.branchName}`
			: isChineseUi
				? "已合并分支结论"
				: "Merged branch conclusion";
		const childThreadId = view.childThreadId;
		const showLink = variant !== "preview" && childThreadId && threadLinks;

		function handleOpenBranch(event: MouseEvent<HTMLAnchorElement>) {
			if (!childThreadId || !threadLinks) return;
			if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
				return;
			}
			event.preventDefault();
			threadLinks.open(childThreadId);
		}

		return (
			<article
				ref={ref}
				aria-label={title}
				id={id}
				tabIndex={-1}
				className={`grid gap-3 rounded-[var(--fa-radius-lg)] border border-l-4 border-[color:var(--fa-border)] border-l-[color:var(--fa-success)] bg-[color:var(--fa-panel-2)] px-4 py-3 text-[color:var(--fa-text)] transition-[outline-color,box-shadow] duration-[var(--fa-dur-fast)] ${
					isHighlighted
						? "shadow-[var(--fa-shadow-md)] outline outline-2 outline-offset-2 outline-[color:var(--fa-success)]"
						: ""
				}`}
			>
				<header className="flex flex-wrap items-baseline justify-between gap-2">
					<h3 className="m-0 text-[length:var(--fa-fs-sm)] font-semibold leading-[var(--fa-lh-tight)]">
						{title}
					</h3>
					{showLink ? (
						<a
							className={`text-[length:var(--fa-fs-xs)] font-semibold ${linkClass}`}
							href={threadLinks.href(childThreadId)}
							onClick={handleOpenBranch}
						>
							{isChineseUi ? "查看分支" : "Open branch"}
						</a>
					) : null}
				</header>

				{view.summary ? (
					<p className="m-0 whitespace-pre-wrap text-[length:var(--fa-fs-sm)] leading-[var(--fa-lh-normal)]">
						{view.summary}
					</p>
				) : null}

				{view.legacyBody ? (
					<div className="fa-message-content">
						<MessageMarkdown isChineseUi={isChineseUi} text={view.legacyBody} />
					</div>
				) : null}

				<ImportList
					items={view.keyFindings}
					label={isChineseUi ? "关键发现" : "Key findings"}
				/>
				<ImportList
					items={view.openQuestions}
					label={isChineseUi ? "开放问题" : "Open questions"}
				/>
				<ImportList
					items={view.evidenceRefs}
					label={isChineseUi ? "证据引用" : "Evidence"}
					renderItem={(item) =>
						isUrl(item) ? (
							<a
								className={linkClass}
								href={item}
								rel="noreferrer noopener"
								target="_blank"
							>
								{item}
							</a>
						) : (
							item
						)
					}
				/>
				<ImportList
					items={view.artifacts}
					label={isChineseUi ? "产物" : "Artifacts"}
				/>
			</article>
		);
	},
);
