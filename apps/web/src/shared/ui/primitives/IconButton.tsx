import { type ButtonHTMLAttributes, forwardRef } from "react";
import {
	type ButtonVariant,
	buttonVariant,
	cx,
	focusRing,
	type PrimitiveSize,
} from "./_shared";

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
