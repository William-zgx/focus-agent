import type { ComponentPropsWithoutRef } from "react";
import { type BadgeTone, badgeTone, cx } from "./_shared";

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
