import { useState } from "react";

import {
	editMessageLabel,
	mergedBranchReadOnlyLabel,
	messageCopyLabel,
} from "./message-list-helpers";

function CopyButton({
	label,
	onCopy,
}: {
	label: string;
	onCopy: () => Promise<void> | void;
}) {
	return (
		<button
			className="fa-message-action-button"
			onClick={() => void onCopy()}
			type="button"
		>
			<span className="fa-message-action-icon" aria-hidden="true">
				<svg aria-hidden="true" viewBox="0 0 20 20">
					<path
						d="M7 5.2A2.2 2.2 0 0 1 9.2 3h5.6A2.2 2.2 0 0 1 17 5.2v7.6a2.2 2.2 0 0 1-2.2 2.2H9.2A2.2 2.2 0 0 1 7 12.8V5.2Z"
						fill="none"
						stroke="currentColor"
						strokeWidth="1.5"
					/>
					<path
						d="M5.2 7H5A2 2 0 0 0 3 9v6a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-.2"
						fill="none"
						stroke="currentColor"
						strokeWidth="1.5"
					/>
				</svg>
			</span>
			<span className="sr-only">{label}</span>
		</button>
	);
}

function EditButton({
	disabled = false,
	label,
	onEdit,
	title,
}: {
	disabled?: boolean;
	label: string;
	onEdit: () => void;
	title?: string;
}) {
	return (
		<button
			aria-label={title || label}
			className="fa-message-action-button"
			disabled={disabled}
			onClick={onEdit}
			title={title || label}
			type="button"
		>
			<span className="fa-message-action-icon" aria-hidden="true">
				<svg aria-hidden="true" viewBox="0 0 20 20">
					<path
						d="M5.7 13.9 4.9 17l3.1-.8 7.1-7.1-2.3-2.3-7.1 7.1Z"
						fill="none"
						stroke="currentColor"
						strokeWidth="1.6"
						strokeLinejoin="round"
					/>
					<path
						d="m11.9 5.8 2.3 2.3 1.4-1.4a1.6 1.6 0 0 0 0-2.3l-.1-.1a1.6 1.6 0 0 0-2.3 0l-1.3 1.5Z"
						fill="currentColor"
					/>
				</svg>
			</span>
			<span className="sr-only">{title || label}</span>
		</button>
	);
}

export function MessageActions({
	content,
	isChineseUi,
	isReadOnly = false,
	onEdit,
}: {
	content: string;
	isChineseUi: boolean;
	isReadOnly?: boolean;
	onEdit?: (() => void) | null;
}) {
	const [copied, setCopied] = useState(false);
	const editTitle = isReadOnly
		? mergedBranchReadOnlyLabel(isChineseUi)
		: editMessageLabel(isChineseUi);

	async function handleCopy() {
		await navigator.clipboard.writeText(content);
		setCopied(true);
		window.setTimeout(() => setCopied(false), 1200);
	}

	return (
		<div className="fa-message-actions">
			<CopyButton
				label={messageCopyLabel(isChineseUi, copied)}
				onCopy={() => void handleCopy()}
			/>
			{onEdit ? (
				<EditButton
					disabled={isReadOnly}
					label={editMessageLabel(isChineseUi)}
					onEdit={onEdit}
					title={editTitle}
				/>
			) : null}
		</div>
	);
}
