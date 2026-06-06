import { useState } from "react";

import type {
	ProcessingStepEntry,
	ToolActivityItem,
} from "./message-transcript";
import {
	processingStepsSummaryLabel,
	toolActivityNote,
	toolActivityTitle,
	toolDetailsToggleLabel,
	toolLabel,
	toolSummaryLabel,
} from "./message-list-helpers";
import { CodeBlock } from "./message-markdown";

const MAX_FAILED_TIMELINE_STEPS = 3;
const MAX_RECENT_TIMELINE_STEPS = 4;
const MAX_DETAIL_PREVIEW_LENGTH = 140;

type ActivityChipTone =
	| "neutral"
	| "skill"
	| "tool"
	| "success"
	| "warn"
	| "danger";
type ActivitySummaryChip = {
	id: string;
	label: string;
	tone: ActivityChipTone;
	value?: number;
};

function processingStepStatusLabel(
	step: ProcessingStepEntry,
	isChineseUi: boolean,
) {
	if (step.status === "failed") {
		return isChineseUi ? "失败" : "Failed";
	}
	if (step.status === "completed") {
		return isChineseUi ? "完成" : "Done";
	}
	if (step.status === "running") {
		return isChineseUi ? "处理中" : "Running";
	}
	return isChineseUi ? "等待中" : "Pending";
}

function compactTimelineSteps(steps: ProcessingStepEntry[]) {
	if (steps.length <= MAX_FAILED_TIMELINE_STEPS + MAX_RECENT_TIMELINE_STEPS) {
		return {
			hiddenCount: 0,
			steps,
		};
	}

	const selectedIds = new Set<string>();
	const firstStep = steps[0];
	if (firstStep?.id.endsWith("-skill-selection")) {
		selectedIds.add(firstStep.id);
	}
	for (const step of steps
		.filter((item) => item.status === "failed")
		.slice(-MAX_FAILED_TIMELINE_STEPS)) {
		selectedIds.add(step.id);
	}
	for (const step of steps.slice(-MAX_RECENT_TIMELINE_STEPS)) {
		selectedIds.add(step.id);
	}

	const visibleSteps = steps.filter((step) => selectedIds.has(step.id));
	return {
		hiddenCount: steps.length - visibleSteps.length,
		steps: visibleSteps,
	};
}

function countSteps(
	steps: ProcessingStepEntry[],
	status: ProcessingStepEntry["status"],
) {
	return steps.filter((step) => step.status === status).length;
}

function activityStatusCounts(steps: ProcessingStepEntry[]) {
	return {
		completed: countSteps(steps, "completed"),
		failed: countSteps(steps, "failed"),
		running: countSteps(steps, "running") + countSteps(steps, "pending"),
	};
}

function activityStats(activity: ToolActivityItem, isChineseUi: boolean) {
	const counts = activityStatusCounts(activity.steps);

	return [
		{
			id: "skills",
			label: "Skill",
			tone: "neutral",
			value: activity.skillIds.length,
		},
		{
			id: "steps",
			label: isChineseUi ? "步骤" : "Steps",
			tone: "neutral",
			value: activity.steps.length,
		},
		{
			id: "tools",
			label: isChineseUi ? "工具" : "Tools",
			tone: "neutral",
			value: activity.toolNames.length,
		},
		{
			id: "details",
			label: isChineseUi ? "详情" : "Details",
			tone: "neutral",
			value: activity.details.length,
		},
		{
			id: "completed",
			label: isChineseUi ? "完成" : "Done",
			tone: "success",
			value: counts.completed,
		},
		{
			id: "running",
			label: isChineseUi ? "处理中" : "Running",
			tone: "warn",
			value: counts.running,
		},
		{
			id: "failed",
			label: isChineseUi ? "失败" : "Failed",
			tone: "danger",
			value: counts.failed,
		},
	].filter((item) => item.value > 0 || item.id === "steps");
}

function statusChipLabel(label: string, value: number, isChineseUi: boolean) {
	return isChineseUi ? `${label} ${value}` : `${value} ${label}`;
}

function activitySummaryChips(
	activity: ToolActivityItem,
	isChineseUi: boolean,
): Array<{ id: string; label: string; tone: ActivityChipTone }> {
	const counts = activityStatusCounts(activity.steps);
	const skillChips: ActivitySummaryChip[] = activity.skillIds.map(
		(skillId) => ({
			id: `skill-${skillId}`,
			label: `Skill · ${skillId}`,
			tone: "skill" as const,
		}),
	);
	const toolChips: ActivitySummaryChip[] = activity.toolNames.map(
		(toolName) => ({
			id: `tool-${toolName}`,
			label: `${isChineseUi ? "工具" : "Tool"} · ${toolName}`,
			tone: "tool" as const,
		}),
	);

	const chips: ActivitySummaryChip[] = [
		...skillChips,
		...toolChips,
		{
			id: "completed",
			value: counts.completed,
			label: statusChipLabel(
				isChineseUi ? "完成" : "done",
				counts.completed,
				isChineseUi,
			),
			tone: "success" as const,
		},
		{
			id: "running",
			value: counts.running,
			label: statusChipLabel(
				isChineseUi ? "处理中" : "running",
				counts.running,
				isChineseUi,
			),
			tone: "warn" as const,
		},
		{
			id: "failed",
			value: counts.failed,
			label: statusChipLabel(
				isChineseUi ? "失败" : "failed",
				counts.failed,
				isChineseUi,
			),
			tone: "danger" as const,
		},
	];
	return chips
		.filter((chip) => chip.value === undefined || chip.value > 0)
		.map(({ value: _value, ...chip }) => chip);
}

function skillSelectionStep(
	activity: ToolActivityItem,
	isChineseUi: boolean,
): ProcessingStepEntry | null {
	if (activity.skillIds.length === 0) {
		return null;
	}
	return {
		id: `${activity.id}-skill-selection`,
		kind: "skill",
		label: isChineseUi
			? `选择 Skill：${activity.skillIds.join("、")}`
			: `Selected skill: ${activity.skillIds.join(", ")}`,
		status: "completed",
		tone: "success",
	};
}

function timelineStepsForActivity(
	activity: ToolActivityItem,
	isChineseUi: boolean,
) {
	const firstStep = skillSelectionStep(activity, isChineseUi);
	return firstStep ? [firstStep, ...activity.steps] : activity.steps;
}

function hiddenStepsLabel(count: number, isChineseUi: boolean) {
	if (isChineseUi) {
		return `隐藏 ${count} 个中间步骤`;
	}
	return `${count} intermediate steps hidden`;
}

function moreStepsToggleLabel(
	count: number,
	isExpanded: boolean,
	isChineseUi: boolean,
) {
	if (isExpanded) {
		return isChineseUi ? "隐藏中间步骤" : "Less steps";
	}
	return isChineseUi ? `查看其他 ${count} 个步骤` : `${count} more steps`;
}

function detailSectionLabel(count: number, isChineseUi: boolean) {
	if (isChineseUi) {
		return `工具详情（${count}）`;
	}
	return `Tool details (${count})`;
}

function detailPreview(content: string) {
	const normalized = content.replace(/\s+/g, " ").trim();
	if (normalized.length <= MAX_DETAIL_PREVIEW_LENGTH) {
		return normalized;
	}
	return `${normalized.slice(0, MAX_DETAIL_PREVIEW_LENGTH - 1).trimEnd()}…`;
}

function detailToggleLabel(isChineseUi: boolean) {
	return isChineseUi ? "展开" : "Open";
}

function ProcessingStepRow({
	isChineseUi,
	step,
}: {
	isChineseUi: boolean;
	step: ProcessingStepEntry;
}) {
	return (
		<div className={`fa-tool-activity-step is-${step.tone}`}>
			<span className="fa-tool-activity-step-dot" />
			<span className="fa-tool-activity-step-main">
				<span className="fa-tool-activity-step-title">{step.label}</span>
				{step.content ? (
					<span className="fa-tool-activity-step-content">{step.content}</span>
				) : null}
			</span>
			<span className="fa-tool-activity-step-status">
				{processingStepStatusLabel(step, isChineseUi)}
			</span>
		</div>
	);
}

export function ToolActivityCard({
	activity,
	isChineseUi,
	note,
	title,
}: {
	activity: ToolActivityItem;
	isChineseUi: boolean;
	note?: string;
	title?: string;
}) {
	const [isOpen, setIsOpen] = useState(false);
	const [showAllSteps, setShowAllSteps] = useState(false);
	const timelineSteps = timelineStepsForActivity(activity, isChineseUi);
	const compactSteps = compactTimelineSteps(timelineSteps);
	const stats = activityStats(activity, isChineseUi);
	const summaryChips = activitySummaryChips(activity, isChineseUi);
	const visibleSteps =
		showAllSteps && compactSteps.hiddenCount > 0
			? timelineSteps
			: compactSteps.steps;

	return (
		<div className="fa-message-row is-assistant assistant">
			<div className="fa-message-stack fa-tool-activity-stack">
				<details
					className="fa-tool-activity-card"
					onToggle={(event) =>
						setIsOpen((event.currentTarget as HTMLDetailsElement).open)
					}
				>
					<summary className="fa-tool-activity-summary">
						<span className="fa-tool-activity-badge">
							{toolLabel(isChineseUi)}
						</span>
						<span className="fa-tool-activity-copy">
							<span className="fa-tool-activity-title">
								{title ?? toolActivityTitle(activity.toolNames, isChineseUi)}
							</span>
							<span className="fa-tool-activity-note">
								{note ?? toolActivityNote(activity.toolNames, isChineseUi)}
							</span>
							{summaryChips.length > 0 ? (
								<span className="fa-tool-activity-preview">
									{summaryChips.map((chip) => (
										<span
											key={chip.id}
											className={`fa-tool-activity-preview-step is-${chip.tone}`}
										>
											{chip.label}
										</span>
									))}
								</span>
							) : null}
						</span>
						<span className="fa-tool-activity-toggle">
							{toolDetailsToggleLabel(isChineseUi, isOpen)}
						</span>
					</summary>

					<div className="fa-tool-activity-body">
						<div className="fa-tool-activity-overview">
							<div className="fa-tool-activity-stats">
								{stats.map((stat) => (
									<span
										key={stat.id}
										className={`fa-tool-activity-stat is-${stat.tone}`}
									>
										<span className="fa-tool-activity-stat-value">
											{stat.value}
										</span>
										<span className="fa-tool-activity-stat-label">
											{stat.label}
										</span>
									</span>
								))}
							</div>

							{activity.summaryText ? (
								<div className="fa-tool-activity-summary-block">
									<div className="fa-tool-activity-summary-label">
										{toolSummaryLabel(isChineseUi)}
									</div>
									<p>{activity.summaryText}</p>
								</div>
							) : null}
						</div>

						{visibleSteps.length > 0 ? (
							<div className="fa-tool-activity-timeline">
								<div className="fa-tool-activity-section-header">
									<span className="fa-tool-activity-section-title">
										{processingStepsSummaryLabel(
											timelineSteps.length,
											isChineseUi,
										)}
									</span>
									{compactSteps.hiddenCount > 0 ? (
										<span className="fa-tool-activity-section-note">
											{hiddenStepsLabel(compactSteps.hiddenCount, isChineseUi)}
										</span>
									) : null}
								</div>
								<div className="fa-tool-activity-steps">
									{visibleSteps.map((step) => (
										<ProcessingStepRow
											key={step.id}
											isChineseUi={isChineseUi}
											step={step}
										/>
									))}
								</div>
								{compactSteps.hiddenCount > 0 ? (
									<button
										className="fa-tool-activity-more-steps"
										onClick={() => setShowAllSteps((value) => !value)}
										type="button"
									>
										{moreStepsToggleLabel(
											compactSteps.hiddenCount,
											showAllSteps,
											isChineseUi,
										)}
									</button>
								) : null}
							</div>
						) : null}

						{activity.details.length > 0 ? (
							<div className="fa-tool-activity-detail-list">
								<div className="fa-tool-activity-section-header">
									<span className="fa-tool-activity-section-title">
										{detailSectionLabel(activity.details.length, isChineseUi)}
									</span>
								</div>

								{activity.details.map((detail) => (
									<details key={detail.id} className="fa-tool-activity-detail">
										<summary className="fa-tool-activity-detail-summary">
											<span className="fa-tool-activity-detail-copy">
												<span className="fa-tool-activity-detail-title">
													{detail.label}
												</span>
												<span className="fa-tool-activity-detail-preview">
													{detailPreview(detail.content)}
												</span>
											</span>
											<span className="fa-tool-activity-detail-meta">
												<span className="fa-tool-activity-detail-language">
													{detail.language || "text"}
												</span>
												<span className="fa-tool-activity-detail-toggle">
													{detailToggleLabel(isChineseUi)}
												</span>
											</span>
										</summary>
										<div className="fa-tool-activity-detail-body">
											<CodeBlock
												code={detail.content}
												isChineseUi={isChineseUi}
												language={detail.language}
											/>
										</div>
									</details>
								))}
							</div>
						) : null}
					</div>
				</details>
			</div>
		</div>
	);
}
