import type { FocusAgentTrajectoryTurnSummary } from "@focus-agent/web-sdk";
import { useEffect, useMemo, useState } from "react";

export function useTrajectoryBatchSelection(
	orderedItems: FocusAgentTrajectoryTurnSummary[],
) {
	const [selectedBatchTurnIds, setSelectedBatchTurnIds] = useState<string[]>(
		[],
	);
	const orderedItemIds = useMemo(
		() => new Set(orderedItems.map((item) => item.id)),
		[orderedItems],
	);
	const selectedBatchItems = useMemo(
		() => orderedItems.filter((item) => selectedBatchTurnIds.includes(item.id)),
		[orderedItems, selectedBatchTurnIds],
	);
	const selectedBatchIdSet = useMemo(
		() => new Set(selectedBatchTurnIds),
		[selectedBatchTurnIds],
	);

	useEffect(() => {
		setSelectedBatchTurnIds((current) =>
			current.filter((turnId) => orderedItemIds.has(turnId)),
		);
	}, [orderedItemIds]);

	function toggleBatchSelection(turnId: string) {
		setSelectedBatchTurnIds((current) =>
			current.includes(turnId)
				? current.filter((item) => item !== turnId)
				: [...current, turnId],
		);
	}

	function selectVisibleBatch() {
		setSelectedBatchTurnIds(orderedItems.map((item) => item.id));
	}

	function selectVisibleFailuresBatch() {
		setSelectedBatchTurnIds(
			orderedItems
				.filter((item) => item.status !== "succeeded" || item.error)
				.map((item) => item.id),
		);
	}

	function clearBatchSelection() {
		setSelectedBatchTurnIds([]);
	}

	return {
		clearBatchSelection,
		selectVisibleBatch,
		selectVisibleFailuresBatch,
		selectedBatchIdSet,
		selectedBatchItems,
		selectedBatchTurnIds,
		toggleBatchSelection,
	};
}
