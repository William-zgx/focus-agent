import type { ReactNode } from "react";

export interface TrajectoryResultConsoleProps {
	isChineseUi: boolean;
}

export function ActionDetailsDisclosure({
	children,
	expanded,
	onExpandedChange,
	summary,
}: {
	children: ReactNode;
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
	summary: string;
}) {
	return (
		<details
			className="fa-observability-action-disclosure"
			open={expanded}
			onToggle={(event) =>
				onExpandedChange((event.currentTarget as HTMLDetailsElement).open)
			}
		>
			<summary>{summary}</summary>
			{children}
		</details>
	);
}

export function ActionResultSnippet({
	label,
	value,
}: {
	label: string;
	value: string;
}) {
	return (
		<div className="fa-observability-action-snippet">
			<span>{label}</span>
			<pre>{value}</pre>
		</div>
	);
}
