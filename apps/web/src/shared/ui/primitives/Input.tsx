import {
	forwardRef,
	type InputHTMLAttributes,
	type SelectHTMLAttributes,
	type TextareaHTMLAttributes,
} from "react";
import { cx, fieldClass, focusRing } from "./_shared";

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
