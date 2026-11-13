import { type ButtonHTMLAttributes, forwardRef } from "react";
import {
	type ButtonVariant,
	buttonVariant,
	cx,
	focusRing,
	type PrimitiveSize,
} from "./_shared";

const controlSize: Record<PrimitiveSize, string> = {
	sm: "min-h-8 px-3 text-[length:var(--fa-fs-xs)]",
	md: "min-h-10 px-4 text-[length:var(--fa-fs-sm)]",
	lg: "min-h-12 px-5 text-[length:var(--fa-fs-md)]",
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
