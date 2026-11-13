import type { ComponentPropsWithoutRef } from "react";
import { cx } from "./_shared";

type SurfaceTone = "panel" | "section";

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
