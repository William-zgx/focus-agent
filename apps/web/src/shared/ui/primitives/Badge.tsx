import type { ComponentPropsWithoutRef } from "react";
import { type BadgeTone, badgeTone, cx } from "./_shared";

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
