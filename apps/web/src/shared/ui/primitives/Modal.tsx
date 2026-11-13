import {
	type ComponentPropsWithoutRef,
	type ReactNode,
	useEffect,
	useId,
} from "react";
import { cx } from "./_shared";

export interface ModalProps
	extends Omit<ComponentPropsWithoutRef<"div">, "title"> {
	onClose?: () => void;
	open: boolean;
	title?: ReactNode;
}

export function Modal({
	children,
	className,
	onClose,
	open,
	title,
	...props
}: ModalProps) {
	const titleId = useId();
	useEffect(() => {
		if (!open || !onClose) return;
		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				onClose();
			}
		};
		document.addEventListener("keydown", handleKeyDown);
		return () => document.removeEventListener("keydown", handleKeyDown);
	}, [onClose, open]);
	if (!open) return null;
	return (
		<div className="fixed inset-0 z-[var(--fa-z-modal)] grid place-items-center p-4">
			<button
				type="button"
				aria-label="Close modal"
				tabIndex={-1}
				className="absolute inset-0 bg-[color:var(--fa-backdrop)]"
				onClick={() => onClose?.()}
			/>
			<div
				role="dialog"
				aria-modal="true"
				aria-labelledby={title ? titleId : undefined}
				aria-label={typeof title === "string" ? title : undefined}
				className={cx(
					"relative max-h-[90vh] w-full max-w-2xl overflow-auto rounded-[var(--fa-radius-lg)] border border-[color:var(--fa-border)] bg-[color:var(--fa-panel-1)] shadow-[var(--fa-shadow-lg)]",
					className,
				)}
				{...props}
			>
				{title ? (
					<div
						id={titleId}
						className="border-b border-[color:var(--fa-border-subtle)] px-5 py-4 text-[length:var(--fa-fs-lg)] font-semibold"
					>
						{title}
					</div>
				) : null}
				<div className="p-5">{children}</div>
			</div>
		</div>
	);
}

export interface DrawerProps extends ModalProps {
	side?: "left" | "right";
}

export function Drawer({
	children,
	className,
	onClose,
	open,
	side = "right",
	title,
	...props
}: DrawerProps) {
	const titleId = useId();
	useEffect(() => {
		if (!open || !onClose) return;
		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				onClose();
			}
		};
		document.addEventListener("keydown", handleKeyDown);
		return () => document.removeEventListener("keydown", handleKeyDown);
	}, [onClose, open]);
	if (!open) return null;
	return (
		<div className="fixed inset-0 z-[var(--fa-z-modal)]">
			<button
				type="button"
				aria-label="Close drawer"
				tabIndex={-1}
				className="absolute inset-0 bg-[color:var(--fa-backdrop)]"
				onClick={() => onClose?.()}
			/>
			<aside
				role="dialog"
				aria-modal="true"
				aria-labelledby={title ? titleId : undefined}
				aria-label={typeof title === "string" ? title : undefined}
				className={cx(
					"absolute top-0 h-full w-full max-w-xl overflow-auto border-[color:var(--fa-border)] bg-[color:var(--fa-panel-1)] shadow-[var(--fa-shadow-lg)]",
					side === "left" ? "left-0 border-r" : "right-0 border-l",
					className,
				)}
				{...props}
			>
				{title ? (
					<div
						id={titleId}
						className="border-b border-[color:var(--fa-border-subtle)] px-5 py-4 text-[length:var(--fa-fs-lg)] font-semibold"
					>
						{title}
					</div>
				) : null}
				<div className="p-5">{children}</div>
			</aside>
		</div>
	);
}
