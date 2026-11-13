import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cx } from "./_shared";

type CardTone = "flat" | "elevated";

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
