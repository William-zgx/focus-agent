import { type ReactNode, useEffect, useRef } from "react";

const FOCUSABLE_SELECTOR = [
	"a[href]",
	"button:not([disabled])",
	'input:not([disabled]):not([type="hidden"])',
	"select:not([disabled])",
	"textarea:not([disabled])",
	"details > summary:first-of-type",
	'[tabindex]:not([tabindex="-1"])',
	'[contenteditable="true"]',
].join(",");

export function resolveInspectorTabTarget(
	dialog: HTMLElement,
	focusableElements: HTMLElement[],
	activeElement: Element | null,
	shiftKey: boolean,
) {
	if (focusableElements.length === 0) return dialog;
	const first = focusableElements[0];
	const last = focusableElements[focusableElements.length - 1];
	if (activeElement === dialog || !dialog.contains(activeElement)) {
		return shiftKey ? last : first;
	}
	if (shiftKey && activeElement === first) return last;
	if (!shiftKey && activeElement === last) return first;
	return null;
}

export function AgentTeamInspectorDialog({
	children,
	closeLabel,
	id,
	isOpen,
	onClose,
	title,
}: {
	children: ReactNode;
	closeLabel: string;
	id: string;
	isOpen: boolean;
	onClose: () => void;
	title: string;
}) {
	const closeButtonRef = useRef<HTMLButtonElement>(null);
	const dialogRef = useRef<HTMLElement>(null);
	const onCloseRef = useRef(onClose);
	const titleId = `${id}-title`;
	onCloseRef.current = onClose;

	useEffect(() => {
		if (!isOpen) return;
		const previouslyFocused =
			document.activeElement instanceof HTMLElement
				? document.activeElement
				: null;
		const dialog = dialogRef.current;
		(closeButtonRef.current ?? dialog)?.focus();

		function handleKeyDown(event: KeyboardEvent) {
			if (event.key === "Escape") {
				event.preventDefault();
				event.stopPropagation();
				onCloseRef.current();
				return;
			}
			if (event.key !== "Tab" || !dialog) return;
			const focusableElements = [
				...dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
			].filter(
				(element) =>
					!element.hidden &&
					element.getAttribute("aria-hidden") !== "true" &&
					element.getClientRects().length > 0,
			);
			const target = resolveInspectorTabTarget(
				dialog,
				focusableElements,
				document.activeElement,
				event.shiftKey,
			);
			if (!target) return;
			event.preventDefault();
			target.focus();
		}

		document.addEventListener("keydown", handleKeyDown, true);
		return () => {
			document.removeEventListener("keydown", handleKeyDown, true);
			if (previouslyFocused?.isConnected) {
				previouslyFocused.focus();
			}
		};
	}, [isOpen]);

	if (!isOpen) return null;

	return (
		// biome-ignore lint/a11y/noStaticElementInteractions: The overlay closes on backdrop click while the dialog owns keyboard interaction.
		// biome-ignore lint/a11y/useKeyWithClickEvents: Escape dismissal and focus trapping are handled by the dialog lifecycle.
		<div
			className="fa-agent-team-inspector-overlay is-open"
			onClick={(event) => {
				if (event.target === event.currentTarget) onClose();
			}}
		>
			<aside
				aria-labelledby={titleId}
				aria-modal="true"
				className="fa-agent-team-inspector-drawer"
				id={id}
				onKeyDown={(event) => event.stopPropagation()}
				ref={dialogRef}
				role="dialog"
				tabIndex={-1}
			>
				<div className="fa-agent-team-inspector-header">
					<div>
						<span id={titleId}>Inspector</span>
						<strong>{title}</strong>
					</div>
					<button
						className="fa-agent-team-cockpit-button is-secondary"
						onClick={onClose}
						ref={closeButtonRef}
						type="button"
					>
						{closeLabel}
					</button>
				</div>
				{children}
			</aside>
		</div>
	);
}
