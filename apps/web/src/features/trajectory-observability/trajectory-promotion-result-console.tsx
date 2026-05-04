import type { FocusAgentTrajectoryPromotionResponse } from "@focus-agent/web-sdk";

import {
	copyText,
	downloadTextArtifact,
} from "./trajectory-action-panel-helpers";
import {
	ActionDetailsDisclosure,
	ActionResultSnippet,
	type TrajectoryResultConsoleProps,
} from "./trajectory-result-console-parts";

interface PromotionResultConsoleProps extends TrajectoryResultConsoleProps {
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
	promotionResult: FocusAgentTrajectoryPromotionResponse;
}

function PromotionSummary({
	isChineseUi,
	promotionResult,
}: {
	isChineseUi: boolean;
	promotionResult: FocusAgentTrajectoryPromotionResponse;
}) {
	return (
		<div className="fa-observability-action-summary">
			<div>
				<span>{isChineseUi ? "Case ID" : "Case ID"}</span>
				<strong>{promotionResult.case_id}</strong>
			</div>
			<div>
				<span>{isChineseUi ? "来源 Turn" : "Source turn"}</span>
				<strong>{promotionResult.source_turn_id}</strong>
			</div>
		</div>
	);
}

function PromotionCommandBar({
	isChineseUi,
	promotionResult,
}: {
	isChineseUi: boolean;
	promotionResult: FocusAgentTrajectoryPromotionResponse;
}) {
	return (
		<div className="fa-observability-command-bar">
			<button
				className="fa-chat-toolbar-button"
				onClick={() => void copyText(promotionResult.jsonl)}
				type="button"
			>
				{isChineseUi ? "复制 JSONL" : "Copy JSONL"}
			</button>
			<button
				className="fa-chat-toolbar-button"
				onClick={() =>
					downloadTextArtifact(
						`${promotionResult.case_id}.jsonl`,
						`${promotionResult.jsonl}\n`,
						"application/x-ndjson",
					)
				}
				type="button"
			>
				{isChineseUi ? "下载 JSONL" : "Download JSONL"}
			</button>
		</div>
	);
}

export function PromotionResultConsole({
	expanded,
	isChineseUi,
	onExpandedChange,
	promotionResult,
}: PromotionResultConsoleProps) {
	return (
		<div className="fa-observability-action-console">
			<div className="fa-inline-notice is-success">
				{isChineseUi
					? "Promote skeleton 预览已生成（未写入）。"
					: "Promotion skeleton preview generated (not written)."}
			</div>
			<PromotionSummary
				isChineseUi={isChineseUi}
				promotionResult={promotionResult}
			/>
			<ActionDetailsDisclosure
				expanded={expanded}
				onExpandedChange={onExpandedChange}
				summary={isChineseUi ? "展开 Promote 详情" : "Show promotion details"}
			>
				<div className="fa-observability-action-console">
					<PromotionCommandBar
						isChineseUi={isChineseUi}
						promotionResult={promotionResult}
					/>
					<ActionResultSnippet
						label={isChineseUi ? "Promote Skeleton" : "Promotion skeleton"}
						value={promotionResult.jsonl}
					/>
				</div>
			</ActionDetailsDisclosure>
		</div>
	);
}
