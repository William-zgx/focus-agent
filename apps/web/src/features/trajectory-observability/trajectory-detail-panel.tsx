import type { FocusAgentTrajectoryTurnDetail } from "@focus-agent/web-sdk";

import {
	EvidenceStage,
	ReviewSummaryCard,
	type SelectedSignals,
	StoryGrid,
	type SupplementalContextItem,
	SupplementalContextPanel,
} from "./trajectory-detail-sections";
import { TrajectoryEmptyState } from "./trajectory-states";
import type { EvidenceMode, ReviewSummary } from "./trajectory-utils";

type TrajectoryDetailPanelProps = {
	correlationCoverage: number;
	evidenceMode: EvidenceMode;
	isChineseUi: boolean;
	isDetailLoading: boolean;
	resultSummary: string;
	reviewSummary: ReviewSummary | null;
	selected: FocusAgentTrajectoryTurnDetail | null;
	selectedSignals: SelectedSignals;
	selectedTurnId: string;
	supplementalContext: SupplementalContextItem[];
};

export function TrajectoryDetailPanel({
	correlationCoverage,
	evidenceMode,
	isChineseUi,
	isDetailLoading,
	resultSummary,
	reviewSummary,
	selected,
	selectedSignals,
	selectedTurnId,
	supplementalContext,
}: TrajectoryDetailPanelProps) {
	if (!selectedTurnId) {
		return <TrajectoryEmptyState isChineseUi={isChineseUi} kind="pick-case" />;
	}
	if (isDetailLoading) {
		return (
			<div className="fa-inline-notice">
				{isChineseUi ? "正在加载 turn 详情..." : "Loading turn detail..."}
			</div>
		);
	}
	if (!selected) {
		return (
			<TrajectoryEmptyState isChineseUi={isChineseUi} kind="unavailable-turn" />
		);
	}

	return (
		<>
			{reviewSummary ? (
				<ReviewSummaryCard
					isChineseUi={isChineseUi}
					reviewSummary={reviewSummary}
				/>
			) : null}

			<EvidenceStage
				correlationCoverage={correlationCoverage}
				evidenceMode={evidenceMode}
				isChineseUi={isChineseUi}
				resultSummary={resultSummary}
				selected={selected}
				selectedSignals={selectedSignals}
			/>
			<StoryGrid
				isChineseUi={isChineseUi}
				resultSummary={resultSummary}
				selected={selected}
			/>
			<SupplementalContextPanel
				isChineseUi={isChineseUi}
				selected={selected}
				supplementalContext={supplementalContext}
			/>
		</>
	);
}
