import { useState } from "react";

import type {
	ProcessingStepEntry,
	ToolActivityItem,
} from "./message-transcript";
import {
	toolActivityNote,
	toolActivityTitle,
	toolDetailsToggleLabel,
	toolLabel,
	toolSummaryLabel,
} from "./message-list-helpers";
import { CodeBlock } from "./message-markdown";

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
	const previewSteps = briefSteps(activity.steps);

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
						{activity.steps.length > 0 ? (
							<div className="fa-tool-activity-steps">
								{activity.steps.map((step) => (
									<ProcessingStepRow
										key={step.id}
										isChineseUi={isChineseUi}
										step={step}
									/>
								))}
							</div>
						) : null}

						{activity.summaryText ? (
							<div className="fa-tool-activity-summary-block">
								<div className="fa-tool-activity-summary-label">
									{toolSummaryLabel(isChineseUi)}
								</div>
								<p>{activity.summaryText}</p>
							</div>
						) : null}

						{activity.details.map((detail) => (
							<div key={detail.id} className="fa-tool-activity-detail">
								<div className="fa-tool-activity-detail-label">
									{detail.label}
								</div>
								<CodeBlock
									code={detail.content}
									isChineseUi={isChineseUi}
									language={detail.language}
								/>
							</div>
						))}
					</div>
				</details>
			</div>
		</div>
	);
}
