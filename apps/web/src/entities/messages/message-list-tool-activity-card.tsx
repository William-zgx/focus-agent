import { useState } from "react";

import type { ToolActivityItem } from "./message-transcript";
import {
	toolActivityNote,
	toolActivityTitle,
	toolDetailsToggleLabel,
	toolLabel,
	toolSummaryLabel,
} from "./message-list-helpers";
import { CodeBlock } from "./message-markdown";

export function ToolActivityCard({
	activity,
	isChineseUi,
}: {
	activity: ToolActivityItem;
	isChineseUi: boolean;
}) {
	const [isOpen, setIsOpen] = useState(false);

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
								{toolActivityTitle(activity.toolNames, isChineseUi)}
							</span>
							<span className="fa-tool-activity-note">
								{toolActivityNote(activity.toolNames, isChineseUi)}
							</span>
						</span>
						<span className="fa-tool-activity-toggle">
							{toolDetailsToggleLabel(isChineseUi, isOpen)}
						</span>
					</summary>

					<div className="fa-tool-activity-body">
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
