export type PrimitiveSize = "sm" | "md" | "lg";
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type BadgeTone =
	| "status"
	| "role"
	| "info"
	| "warning"
	| "danger"
	| "success";

export function cx(...values: Array<string | false | null | undefined>) {
	return values.filter(Boolean).join(" ");
}

export const focusRing =
	"focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fa-focus-ring)]";

export const buttonVariant: Record<ButtonVariant, string> = {
	primary:
		"border-[color:var(--fa-accent)] bg-[image:var(--fa-gradient-brand)] text-[color:var(--fa-user-bubble-text)] shadow-[var(--fa-shadow-sm)] hover:shadow-[var(--fa-shadow-md)]",
	secondary:
		"border-[color:var(--fa-border)] bg-[color:var(--fa-panel-3)] text-[color:var(--fa-text)] hover:border-[color:var(--fa-border-strong)] hover:bg-[color:var(--fa-panel-4)]",
	ghost:
		"border-transparent bg-transparent text-[color:var(--fa-text-muted)] hover:bg-[color:var(--fa-panel-2)] hover:text-[color:var(--fa-text)]",
	danger:
		"border-[color:var(--fa-danger)] bg-[color:var(--fa-danger-surface)] text-[color:var(--fa-status-danger-text)] hover:bg-[color:var(--fa-danger-surface-strong)]",
};

export const fieldClass =
	"w-full rounded-[var(--fa-radius-md)] border border-[color:var(--fa-border)] bg-[color:var(--fa-panel-1)] px-3 py-2 text-[length:var(--fa-fs-sm)] leading-[var(--fa-lh-normal)] text-[color:var(--fa-text)] placeholder:text-[color:var(--fa-text-soft)] disabled:cursor-not-allowed disabled:opacity-60";

export const badgeTone: Record<BadgeTone, string> = {
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
