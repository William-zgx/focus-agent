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

function briefSteps(steps: ProcessingStepEntry[]) {
	if (steps.length <= 2) {
		return steps;
	}
	const failed = steps.find((step) => step.status === "failed");
	const latest = steps[steps.length - 1];
	if (failed && failed.id !== latest.id) {
		return [failed, latest];
	}
	return steps.slice(-2);
}

function compactTimelineSteps(steps: ProcessingStepEntry[]) {
	if (steps.length <= MAX_FAILED_TIMELINE_STEPS + MAX_RECENT_TIMELINE_STEPS) {
		return {
			hiddenCount: 0,
			steps,
		};
	}

	const selectedIds = new Set<string>();
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

function activityStats(activity: ToolActivityItem, isChineseUi: boolean) {
	const failedCount = countSteps(activity.steps, "failed");
	const runningCount = countSteps(activity.steps, "running");
	const completedCount = countSteps(activity.steps, "completed");
	const pendingCount = countSteps(activity.steps, "pending");

	return [
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
			value: completedCount,
		},
		{
			id: "running",
			label: isChineseUi ? "处理中" : "Running",
			tone: "warn",
			value: runningCount + pendingCount,
		},
		{
			id: "failed",
			label: isChineseUi ? "失败" : "Failed",
			tone: "danger",
			value: failedCount,
		},
	].filter((item) => item.value > 0 || item.id === "steps");
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
	const compactSteps = compactTimelineSteps(activity.steps);
	const previewSteps = briefSteps(activity.steps);
	const stats = activityStats(activity, isChineseUi);
	const visibleSteps =
		showAllSteps && compactSteps.hiddenCount > 0
			? activity.steps
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
							{previewSteps.length > 0 ? (
								<span className="fa-tool-activity-preview">
									{previewSteps.map((step) => (
										<span
											key={step.id}
											className={`fa-tool-activity-preview-step is-${step.tone}`}
										>
											{step.label}
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
											activity.steps.length,
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
