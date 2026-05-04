import type { FocusAgentTrajectoryTurnSummary } from "@focus-agent/web-sdk";
import { startTransition, useEffect, type RefObject } from "react";

export function useTrajectoryPageSelectionEffects({
	detailPanelRef,
	isListLoading,
	listError,
	orderedItems,
	selectedTurnId,
	setSelectedTurnId,
}: {
	detailPanelRef: RefObject<HTMLElement | null>;
	isListLoading: boolean;
	listError: unknown;
	orderedItems: FocusAgentTrajectoryTurnSummary[];
	selectedTurnId: string;
	setSelectedTurnId: (turnId: string) => void;
}) {
	useEffect(() => {
		if (!orderedItems.length) {
			if (isListLoading || listError) {
				return;
			}
			setSelectedTurnId("");
			return;
		}
		if (orderedItems.some((item) => item.id === selectedTurnId)) return;
		startTransition(() => {
			setSelectedTurnId(orderedItems[0].id);
		});
	}, [
		isListLoading,
		listError,
		orderedItems,
		selectedTurnId,
		setSelectedTurnId,
	]);

	useEffect(() => {
		void selectedTurnId;
		detailPanelRef.current?.scrollTo({ top: 0, behavior: "auto" });
	}, [detailPanelRef, selectedTurnId]);
}
