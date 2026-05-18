import {
	type ButtonHTMLAttributes,
	type ComponentPropsWithoutRef,
	type InputHTMLAttributes,
	type ReactNode,
	type SelectHTMLAttributes,
	type TextareaHTMLAttributes,
	forwardRef,
	useEffect,
	useId,
} from "react";

type PrimitiveSize = "sm" | "md" | "lg";
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type CardTone = "flat" | "elevated";
type SurfaceTone = "panel" | "section";
type BadgeTone = "status" | "role" | "info" | "warning" | "danger" | "success";

function cx(...values: Array<string | false | null | undefined>) {
	return values.filter(Boolean).join(" ");
}

const focusRing =
	"focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fa-focus-ring)]";

const controlSize: Record<PrimitiveSize, string> = {
	sm: "min-h-8 px-3 text-[length:var(--fa-fs-xs)]",
	md: "min-h-10 px-4 text-[length:var(--fa-fs-sm)]",
	lg: "min-h-12 px-5 text-[length:var(--fa-fs-md)]",
};

const buttonVariant: Record<ButtonVariant, string> = {
	primary:
		"border-[color:var(--fa-accent)] bg-[image:var(--fa-gradient-brand)] text-[color:var(--fa-user-bubble-text)] shadow-[var(--fa-shadow-sm)] hover:shadow-[var(--fa-shadow-md)]",
	secondary:
		"border-[color:var(--fa-border)] bg-[color:var(--fa-panel-3)] text-[color:var(--fa-text)] hover:border-[color:var(--fa-border-strong)] hover:bg-[color:var(--fa-panel-4)]",
	ghost:
		"border-transparent bg-transparent text-[color:var(--fa-text-muted)] hover:bg-[color:var(--fa-panel-2)] hover:text-[color:var(--fa-text)]",
	danger:
		"border-[color:var(--fa-danger)] bg-[color:var(--fa-danger-surface)] text-[color:var(--fa-status-danger-text)] hover:bg-[color:var(--fa-danger-surface-strong)]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
	variant?: ButtonVariant;
	size?: PrimitiveSize;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
	(
		{
			className,
			size = "md",
			type = "button",
			variant = "secondary",
			...props
		},
		ref,
	) => (
		<button
			ref={ref}
			type={type}
			className={cx(
				"inline-flex items-center justify-center gap-2 rounded-[var(--fa-radius-md)] border font-semibold leading-[var(--fa-lh-tight)] transition-[background,border-color,box-shadow,color,transform] duration-[var(--fa-dur-fast)] ease-[var(--fa-ease-standard)] disabled:cursor-not-allowed disabled:opacity-50",
				focusRing,
				controlSize[size],
				buttonVariant[variant],
				className,
			)}
			{...props}
		/>
	),
);
Button.displayName = "Button";

export interface IconButtonProps
	extends ButtonHTMLAttributes<HTMLButtonElement> {
	label: string;
	size?: PrimitiveSize;
	variant?: ButtonVariant;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
	(
		{
			children,
			className,
			label,
			size = "md",
			type = "button",
			variant = "ghost",
			...props
		},
		ref,
	) => (
		<button
			ref={ref}
			type={type}
			aria-label={label}
			title={props.title ?? label}
			className={cx(
				"inline-grid aspect-square place-items-center rounded-[var(--fa-radius-md)] border p-0 transition-[background,border-color,box-shadow,color,transform] duration-[var(--fa-dur-fast)] ease-[var(--fa-ease-standard)] disabled:cursor-not-allowed disabled:opacity-50",
				focusRing,
				size === "sm" ? "h-8 w-8" : size === "lg" ? "h-12 w-12" : "h-10 w-10",
				buttonVariant[variant],
				className,
			)}
			{...props}
		>
			{children}
		</button>
	),
);
IconButton.displayName = "IconButton";

export interface CardProps extends ComponentPropsWithoutRef<"section"> {
	footer?: ReactNode;
	header?: ReactNode;
	tone?: CardTone;
}

export function Card({
	children,
	className,
	footer,
	header,
	tone = "flat",
	...props
}: CardProps) {
	return (
		<section
			className={cx(
				"rounded-[var(--fa-radius-lg)] border border-[color:var(--fa-border)] bg-[color:var(--fa-panel-2)] text-[color:var(--fa-text)]",
				tone === "elevated" ? "shadow-[var(--fa-shadow-md)]" : "",
				className,
			)}
			{...props}
		>
			{header ? (
				<div className="border-b border-[color:var(--fa-border-subtle)] px-5 py-4">
					{header}
				</div>
			) : null}
			<div className="px-5 py-4">{children}</div>
			{footer ? (
				<div className="border-t border-[color:var(--fa-border-subtle)] px-5 py-4">
					{footer}
				</div>
			) : null}
		</section>
	);
}

export interface SurfaceProps extends ComponentPropsWithoutRef<"section"> {
	tone?: SurfaceTone;
}

export function Surface({
	children,
	className,
	tone = "panel",
	...props
}: SurfaceProps) {
	return (
		<section
			className={cx(
				"rounded-[var(--fa-radius-lg)] border text-[color:var(--fa-text)]",
				tone === "section"
					? "border-[color:var(--fa-border-subtle)] bg-[color:var(--fa-panel-1)]"
					: "border-[color:var(--fa-border)] bg-[color:var(--fa-panel-2)] shadow-[var(--fa-shadow-sm)]",
				className,
			)}
			{...props}
		>
			{children}
		</section>
	);
}

const fieldClass =
	"w-full rounded-[var(--fa-radius-md)] border border-[color:var(--fa-border)] bg-[color:var(--fa-panel-1)] px-3 py-2 text-[length:var(--fa-fs-sm)] leading-[var(--fa-lh-normal)] text-[color:var(--fa-text)] placeholder:text-[color:var(--fa-text-soft)] disabled:cursor-not-allowed disabled:opacity-60";

export const Input = forwardRef<
	HTMLInputElement,
	InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
	<input
		ref={ref}
		className={cx(fieldClass, focusRing, className)}
		{...props}
	/>
));
Input.displayName = "Input";

export const Textarea = forwardRef<
	HTMLTextAreaElement,
	TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
	<textarea
		ref={ref}
		className={cx(fieldClass, "min-h-28 resize-y", focusRing, className)}
		{...props}
	/>
));
Textarea.displayName = "Textarea";

export const Select = forwardRef<
	HTMLSelectElement,
	SelectHTMLAttributes<HTMLSelectElement>
>(({ className, ...props }, ref) => (
	<select
		ref={ref}
		className={cx(fieldClass, focusRing, className)}
		{...props}
	/>
));
Select.displayName = "Select";

const badgeTone: Record<BadgeTone, string> = {
	status:
		"border-[color:var(--fa-border)] bg-[color:var(--fa-panel-3)] text-[color:var(--fa-text-muted)]",
	role: "border-[color:var(--fa-border-strong)] bg-[color:var(--fa-accent-surface)] text-[color:var(--fa-accent-text-strong)]",
	info: "border-[color:var(--fa-info)] bg-[color:var(--fa-info-surface)] text-[color:var(--fa-info-text)]",
	warning:
		"border-[color:var(--fa-warning)] bg-[color:var(--fa-warning-surface)] text-[color:var(--fa-status-warning-text)]",
	danger:
		"border-[color:var(--fa-danger)] bg-[color:var(--fa-danger-surface)] text-[color:var(--fa-status-danger-text)]",
	success:
		"border-[color:var(--fa-success)] bg-[color:var(--fa-success-surface)] text-[color:var(--fa-status-success-text)]",
};

export interface BadgeProps extends ComponentPropsWithoutRef<"span"> {
	tone?: BadgeTone;
}

export function Badge({ className, tone = "status", ...props }: BadgeProps) {
	return (
		<span
			className={cx(
				"inline-flex items-center rounded-[var(--fa-radius-pill)] border px-2 py-0.5 text-[length:var(--fa-fs-xs)] font-semibold leading-[var(--fa-lh-tight)]",
				badgeTone[tone],
				className,
			)}
			{...props}
		/>
	);
}

export const Tag = Badge;
export const Chip = Badge;

export interface TabsProps<T extends string> {
	activeId: T;
	className?: string;
	items: Array<{
		disabled?: boolean;
		id: T;
		label: ReactNode;
		panel?: ReactNode;
	}>;
	onChange: (id: T) => void;
}

export function Tabs<T extends string>({
	activeId,
	className,
	items,
	onChange,
}: TabsProps<T>) {
	const active = items.find((item) => item.id === activeId);
	const tabsId = useId();
	const enabledItems = items.filter((item) => !item.disabled);
	const moveFocus = (itemId: T) => {
		const tab = document.getElementById(`${tabsId}-tab-${itemId}`);
		tab?.focus();
	};
	const selectRelativeTab = (itemId: T, offset: number) => {
		if (enabledItems.length === 0) return;
		const currentIndex = Math.max(
			0,
			enabledItems.findIndex((item) => item.id === itemId),
		);
		const next =
			enabledItems[
				(currentIndex + offset + enabledItems.length) % enabledItems.length
			];
		onChange(next.id);
		moveFocus(next.id);
	};
	return (
		<div className={className}>
			<div
				className="inline-flex rounded-[var(--fa-radius-md)] border border-[color:var(--fa-border)] bg-[color:var(--fa-panel-2)] p-1"
				role="tablist"
			>
				{items.map((item) => (
					<button
						key={item.id}
						type="button"
						role="tab"
						id={`${tabsId}-tab-${item.id}`}
						aria-controls={`${tabsId}-panel-${item.id}`}
						aria-selected={item.id === activeId}
						tabIndex={item.id === activeId ? 0 : -1}
						disabled={item.disabled}
						onClick={() => onChange(item.id)}
						onKeyDown={(event) => {
							if (event.key === "ArrowRight" || event.key === "ArrowDown") {
								event.preventDefault();
								selectRelativeTab(item.id, 1);
							}
							if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
								event.preventDefault();
								selectRelativeTab(item.id, -1);
							}
							if (event.key === "Home") {
								event.preventDefault();
								const first = enabledItems[0];
								if (first) {
									onChange(first.id);
									moveFocus(first.id);
								}
							}
							if (event.key === "End") {
								event.preventDefault();
								const last = enabledItems.at(-1);
								if (last) {
									onChange(last.id);
									moveFocus(last.id);
								}
							}
						}}
						className={cx(
							"rounded-[var(--fa-radius-sm)] px-3 py-1.5 text-[length:var(--fa-fs-sm)] font-semibold leading-[var(--fa-lh-tight)] text-[color:var(--fa-text-muted)] transition-colors disabled:opacity-50",
							focusRing,
							item.id === activeId
								? "bg-[color:var(--fa-panel-4)] text-[color:var(--fa-text)]"
								: "hover:text-[color:var(--fa-text)]",
						)}
					>
						{item.label}
					</button>
				))}
			</div>
			{active?.panel ? (
				<div
					id={`${tabsId}-panel-${active.id}`}
					aria-labelledby={`${tabsId}-tab-${active.id}`}
					className="mt-4"
					role="tabpanel"
				>
					{active.panel}
				</div>
			) : null}
		</div>
	);
}

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

export interface ToastProps extends ComponentPropsWithoutRef<"output"> {
	tone?: Exclude<BadgeTone, "role" | "status">;
}

export function Toast({ className, tone = "info", ...props }: ToastProps) {
	return (
		<output
			className={cx(
				"rounded-[var(--fa-radius-md)] border px-4 py-3 text-[length:var(--fa-fs-sm)] shadow-[var(--fa-shadow-md)]",
				badgeTone[tone],
				className,
			)}
			{...props}
		/>
	);
}

export interface EmptyStateProps
	extends Omit<ComponentPropsWithoutRef<"div">, "title"> {
	action?: ReactNode;
	description?: ReactNode;
	icon?: ReactNode;
	title: ReactNode;
}

export function EmptyState({
	action,
	className,
	description,
	icon,
	title,
	...props
}: EmptyStateProps) {
	return (
		<div
			className={cx(
				"grid place-items-center gap-3 rounded-[var(--fa-radius-lg)] border border-dashed border-[color:var(--fa-border)] bg-[color:var(--fa-panel-2)] p-8 text-center",
				className,
			)}
			{...props}
		>
			{icon ? (
				<div className="text-[color:var(--fa-accent-text)]">{icon}</div>
			) : null}
			<div className="text-[length:var(--fa-fs-md)] font-semibold text-[color:var(--fa-text)]">
				{title}
			</div>
			{description ? (
				<div className="max-w-md text-[length:var(--fa-fs-sm)] leading-[var(--fa-lh-normal)] text-[color:var(--fa-text-muted)]">
					{description}
				</div>
			) : null}
			{action ? <div className="pt-1">{action}</div> : null}
		</div>
	);
}

export interface SkeletonProps extends ComponentPropsWithoutRef<"div"> {
	lines?: number;
}

export function Skeleton({ className, lines = 1, ...props }: SkeletonProps) {
	const skeletonLines = Array.from(
		{ length: Math.max(1, lines) },
		(_, index) => ({
			id: `skeleton-line-${index + 1}`,
			width: `${100 - Math.min(index, 3) * 14}%`,
		}),
	);
	return (
		<div className={cx("grid gap-2", className)} aria-hidden="true" {...props}>
			{skeletonLines.map((line) => (
				<div
					key={line.id}
					className="h-3 rounded-[var(--fa-radius-pill)] bg-[color:var(--fa-panel-4)] opacity-70"
					style={{ width: line.width }}
				/>
			))}
		</div>
	);
}
