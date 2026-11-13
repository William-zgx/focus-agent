import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cx } from "./_shared";

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
