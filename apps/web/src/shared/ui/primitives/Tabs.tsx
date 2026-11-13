import { type ReactNode, useId } from "react";
import { cx, focusRing } from "./_shared";

export interface TabsProps<T extends string> {
	activeId: T;
	className?: string;
	items: Array<{
		disabled?: boolean;
		id: T;
		label: ReactNode;
		panel?: ReactNode;
	}>;
	onChange: (id: T) => void;
}

export function Tabs<T extends string>({
	activeId,
	className,
	items,
	onChange,
}: TabsProps<T>) {
	const active = items.find((item) => item.id === activeId);
	const tabsId = useId();
	const enabledItems = items.filter((item) => !item.disabled);
	const moveFocus = (itemId: T) => {
		const tab = document.getElementById(`${tabsId}-tab-${itemId}`);
		tab?.focus();
	};
	const selectRelativeTab = (itemId: T, offset: number) => {
		if (enabledItems.length === 0) return;
		const currentIndex = Math.max(
			0,
			enabledItems.findIndex((item) => item.id === itemId),
		);
		const next =
			enabledItems[
				(currentIndex + offset + enabledItems.length) % enabledItems.length
			];
		onChange(next.id);
		moveFocus(next.id);
	};
	return (
		<div className={className}>
			<div
				className="inline-flex rounded-[var(--fa-radius-md)] border border-[color:var(--fa-border)] bg-[color:var(--fa-panel-2)] p-1"
				role="tablist"
			>
				{items.map((item) => (
					<button
						key={item.id}
						type="button"
						role="tab"
						id={`${tabsId}-tab-${item.id}`}
						aria-controls={`${tabsId}-panel-${item.id}`}
						aria-selected={item.id === activeId}
						tabIndex={item.id === activeId ? 0 : -1}
						disabled={item.disabled}
						onClick={() => onChange(item.id)}
						onKeyDown={(event) => {
							if (event.key === "ArrowRight" || event.key === "ArrowDown") {
								event.preventDefault();
								selectRelativeTab(item.id, 1);
							}
							if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
								event.preventDefault();
								selectRelativeTab(item.id, -1);
							}
							if (event.key === "Home") {
								event.preventDefault();
								const first = enabledItems[0];
								if (first) {
									onChange(first.id);
									moveFocus(first.id);
								}
							}
							if (event.key === "End") {
								event.preventDefault();
								const last = enabledItems[enabledItems.length - 1];
								if (last) {
									onChange(last.id);
									moveFocus(last.id);
								}
							}
						}}
						className={cx(
							"rounded-[var(--fa-radius-sm)] px-3 py-1.5 text-[length:var(--fa-fs-sm)] font-semibold leading-[var(--fa-lh-tight)] text-[color:var(--fa-text-muted)] transition-colors disabled:opacity-50",
							focusRing,
							item.id === activeId
								? "bg-[color:var(--fa-panel-4)] text-[color:var(--fa-text)]"
								: "hover:text-[color:var(--fa-text)]",
						)}
					>
						{item.label}
					</button>
				))}
			</div>
			{active?.panel ? (
				<div
					id={`${tabsId}-panel-${active.id}`}
					aria-labelledby={`${tabsId}-tab-${active.id}`}
					className="mt-4"
					role="tabpanel"
				>
					{active.panel}
				</div>
			) : null}
		</div>
	);
}
