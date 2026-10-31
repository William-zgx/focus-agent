import type { BranchRole } from "@focus-agent/web-sdk";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";

import { roleLabel } from "@/features/branch-tree/branch-tree-helpers";

export type BranchForkRequest = {
	parentThreadId: string;
	parentLabel?: string;
	goalDraft?: string;
	/** Set by a message's "Branch from here": the branch sees nothing after it. */
	forkAtMessageId?: string;
};

export type BranchForkSubmission = {
	branchName: string;
	branchRole?: BranchRole;
	goal: string;
};

type BranchForkDialogProps = {
	errorMessage?: string | null;
	isChineseUi: boolean;
	isSubmitting: boolean;
	onClose: () => void;
	onSubmit: (submission: BranchForkSubmission) => void;
	request: BranchForkRequest | null;
};

const FORK_ROLES: BranchRole[] = [
	"explore_alternatives",
	"deep_dive",
	"execute",
	"verify",
	"writeup",
];

function roleHint(role: BranchRole, isChineseUi: boolean) {
	switch (role) {
		case "explore_alternatives":
			return isChineseUi ? "并行比较其他方案" : "compare other approaches";
		case "deep_dive":
			return isChineseUi ? "专注把一个问题挖透" : "go deep on one question";
		case "execute":
			return isChineseUi ? "动手实现或执行任务" : "carry out a concrete task";
		case "verify":
			return isChineseUi ? "核对结论与证据" : "check claims and evidence";
		case "writeup":
			return isChineseUi ? "整理成文档或报告" : "turn findings into a write-up";
		default:
			return "";
	}
}

const FOCUSABLE =
	'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function BranchForkDialog({
	errorMessage,
	isChineseUi,
	isSubmitting,
	onClose,
	onSubmit,
	request,
}: BranchForkDialogProps) {
	const titleId = useId();
	const descriptionId = useId();
	const dialogRef = useRef<HTMLElement>(null);
	const nameInputRef = useRef<HTMLInputElement>(null);
	const [branchName, setBranchName] = useState("");
	const [branchRole, setBranchRole] = useState<BranchRole | "">("");
	const [goal, setGoal] = useState("");
	const isOpen = Boolean(request);

	useEffect(() => {
		if (!request) return;
		setBranchName("");
		setBranchRole("");
		setGoal(request.goalDraft ?? "");
	}, [request]);

	useEffect(() => {
		if (!isOpen) return;
		const previouslyFocused =
			document.activeElement instanceof HTMLElement
				? document.activeElement
				: null;
		const dialog = dialogRef.current;
		nameInputRef.current?.focus();

		function handleKeyDown(event: KeyboardEvent) {
			if (event.key === "Escape") {
				event.preventDefault();
				onClose();
				return;
			}
			if (event.key !== "Tab" || !dialog) return;
			const focusable = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)];
			const first = focusable[0];
			const last = focusable[focusable.length - 1];
			if (!first || !last) return;
			if (event.shiftKey && document.activeElement === first) {
				event.preventDefault();
				last.focus();
			} else if (!event.shiftKey && document.activeElement === last) {
				event.preventDefault();
				first.focus();
			}
		}

		window.addEventListener("keydown", handleKeyDown);
		return () => {
			window.removeEventListener("keydown", handleKeyDown);
			previouslyFocused?.focus();
		};
	}, [isOpen, onClose]);

	if (!request) return null;

	function handleSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (isSubmitting) return;
		onSubmit({
			branchName: branchName.trim(),
			branchRole: branchRole || undefined,
			goal: goal.trim(),
		});
	}

	const parentText = request.forkAtMessageId
		? isChineseUi
			? "从这条消息处分叉，只继承它及之前的上下文，之后的对话不会带入新分支。"
			: "Forks from this message and inherits only the context up to it; later turns stay out of the branch."
		: request.parentLabel
			? isChineseUi
				? `从「${request.parentLabel}」的最新进度分叉，继承它的上下文。`
				: `Forks from the latest state of "${request.parentLabel}" and inherits its context.`
			: isChineseUi
				? "从当前线程的最新进度分叉，继承它的上下文。"
				: "Forks from the latest state of this thread and inherits its context.";

	return (
		<>
			<button
				aria-label={isChineseUi ? "关闭新建分支" : "Close new branch dialog"}
				className="fa-modal-backdrop"
				onClick={onClose}
				tabIndex={-1}
				type="button"
			/>
			<section
				ref={dialogRef}
				aria-describedby={descriptionId}
				aria-labelledby={titleId}
				aria-modal="true"
				className="fa-focus-modal"
				role="dialog"
			>
				<form
					className="fa-focus-modal-card max-w-[560px]"
					onSubmit={handleSubmit}
				>
					<div className="fa-focus-modal-head">
						<div className="fa-focus-modal-copy">
							<h3 id={titleId}>{isChineseUi ? "新建分支" : "New branch"}</h3>
							<p id={descriptionId}>{parentText}</p>
						</div>
						<button
							aria-label={isChineseUi ? "关闭" : "Close"}
							className="fa-focus-modal-close"
							onClick={onClose}
							type="button"
						>
							×
						</button>
					</div>

					<div className="fa-focus-modal-form">
						<label className="fa-focus-modal-field">
							<span>{isChineseUi ? "分支名称" : "Branch name"}</span>
							<input
								ref={nameInputRef}
								disabled={isSubmitting}
								maxLength={80}
								onChange={(event) => setBranchName(event.target.value)}
								placeholder={
									isChineseUi
										? "留空则根据目标自动命名"
										: "Leave empty to name it from the goal"
								}
								value={branchName}
							/>
						</label>

						<label className="fa-focus-modal-field">
							<span>{isChineseUi ? "分支角色" : "Branch role"}</span>
							<select
								disabled={isSubmitting}
								onChange={(event) =>
									setBranchRole(event.target.value as BranchRole | "")
								}
								value={branchRole}
							>
								<option value="">
									{isChineseUi
										? "自动：根据对话判断"
										: "Auto: infer from the conversation"}
								</option>
								{FORK_ROLES.map((role) => (
									<option key={role} value={role}>
										{`${roleLabel(role, isChineseUi)}${isChineseUi ? "：" : ": "}${roleHint(role, isChineseUi)}`}
									</option>
								))}
							</select>
						</label>

						<label className="fa-focus-modal-field">
							<span>
								{isChineseUi
									? "目标（作为分支的第一条消息发送，可选）"
									: "Goal (sent as the branch's first message, optional)"}
							</span>
							<textarea
								disabled={isSubmitting}
								onChange={(event) => setGoal(event.target.value)}
								placeholder={
									isChineseUi
										? "这个分支要回答什么问题？"
										: "What should this branch figure out?"
								}
								rows={4}
								value={goal}
							/>
						</label>
					</div>

					{errorMessage ? (
						<div className="fa-focus-modal-note is-danger" role="alert">
							{errorMessage}
						</div>
					) : null}

					<div className="fa-focus-modal-actions">
						<button disabled={isSubmitting} onClick={onClose} type="button">
							{isChineseUi ? "取消" : "Cancel"}
						</button>
						<button disabled={isSubmitting} type="submit">
							{isSubmitting
								? isChineseUi
									? "创建中..."
									: "Creating..."
								: goal.trim()
									? isChineseUi
										? "创建并发送目标"
										: "Create and send goal"
									: isChineseUi
										? "创建分支"
										: "Create branch"}
						</button>
					</div>
				</form>
			</section>
		</>
	);
}
