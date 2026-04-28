import type { ReactNode } from "react";

type EmptyStateProps = {
	children?: ReactNode;
	isChineseUi: boolean;
	kind:
		| "no-results"
		| "pick-case"
		| "missing-detail"
		| "unavailable-turn"
		| "rail-placeholder";
	onApplyAllPreset?: () => void;
	onResetFilters?: () => void;
};

const MESSAGES = {
	"no-results": {
		zh: "当前筛选下没有匹配的复盘样本。",
		en: "No trajectory turns match the current filters.",
	},
	"pick-case": {
		zh: "先从左侧样本队列里选一条 case。",
		en: "Pick a case from the sample queue first.",
	},
	"missing-detail": {
		zh: "当前样本的详情暂时不可用。",
		en: "This turn detail is temporarily unavailable.",
	},
	"unavailable-turn": {
		zh: "当前样本不存在或详情尚未可用。",
		en: "This trajectory turn is unavailable.",
	},
	"rail-placeholder": {
		zh: "选择样本后，这里会常驻显示关联锚点、热点工具和 Replay 动作。",
		en: "Select a turn to keep the anchors, hotspots, and replay actions resident in this rail.",
	},
};

export function TrajectoryEmptyState({
	children,
	isChineseUi,
	kind,
	onApplyAllPreset,
	onResetFilters,
}: EmptyStateProps) {
	const message = MESSAGES[kind];
	return (
		<div className="fa-observability-empty">
			{children ?? (isChineseUi ? message.zh : message.en)}
			{kind === "no-results" ? (
				<div className="fa-observability-command-bar">
					{onApplyAllPreset ? (
						<button
							className="fa-chat-toolbar-button"
							onClick={onApplyAllPreset}
							type="button"
						>
							{isChineseUi ? "查看全部样本" : "View all turns"}
						</button>
					) : null}
					{onResetFilters ? (
						<button
							className="fa-chat-toolbar-button"
							onClick={onResetFilters}
							type="button"
						>
							{isChineseUi ? "清空过滤器" : "Clear filters"}
						</button>
					) : null}
				</div>
			) : null}
		</div>
	);
}

export function TrajectoryInlineError({
	isWarning,
	message,
}: {
	isWarning: boolean;
	message: string;
}) {
	return (
		<div
			className={`fa-inline-notice ${isWarning ? "is-warning" : "is-danger"}`.trim()}
		>
			{message}
		</div>
	);
}
