import type { ComponentPropsWithoutRef } from "react";
import { cx } from "./_shared";

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
