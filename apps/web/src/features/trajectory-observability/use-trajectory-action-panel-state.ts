import type {
	FocusAgentTrajectoryBatchPromotionPreviewResponse,
	FocusAgentTrajectoryBatchReplayCompareResponse,
	FocusAgentTrajectoryPromotionResponse,
	FocusAgentTrajectoryReplayResponse,
	FocusAgentTrajectoryTurnDetail,
} from "@focus-agent/web-sdk";
import { useEffect, useMemo, useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import {
	buildTrajectoryActionRequest,
	type RunningTrajectoryAction,
} from "./trajectory-action-panel-helpers";

export function useTrajectoryActionPanelState({
	batchTurnIds,
	hasBatchSelection,
	selected,
}: {
	batchTurnIds: string[];
	hasBatchSelection: boolean;
	selected: FocusAgentTrajectoryTurnDetail | null;
}) {
	const { client } = useFocusAgent();
	const selectedTurnId = selected?.id ?? "";
	const batchTurnIdsKey = useMemo(
		() => batchTurnIds.join("\n"),
		[batchTurnIds],
	);
	const [caseIdPrefix, setCaseIdPrefix] = useState("traj");
	const [copyToolTrajectory, setCopyToolTrajectory] = useState(true);
	const [copyAnswerSubstring, setCopyAnswerSubstring] = useState(false);
	const [answerSubstringChars, setAnswerSubstringChars] = useState("160");
	const [runningAction, setRunningAction] =
		useState<RunningTrajectoryAction | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [singleResultTurnId, setSingleResultTurnId] = useState(selectedTurnId);
	const [batchResultTurnIdsKey, setBatchResultTurnIdsKey] =
		useState(batchTurnIdsKey);
	const [rawReplayResult, setReplayResult] =
		useState<FocusAgentTrajectoryReplayResponse | null>(null);
	const [rawPromotionResult, setPromotionResult] =
		useState<FocusAgentTrajectoryPromotionResponse | null>(null);
	const [rawBatchReplayResult, setBatchReplayResult] =
		useState<FocusAgentTrajectoryBatchReplayCompareResponse | null>(null);
	const [rawBatchPromotionResult, setBatchPromotionResult] =
		useState<FocusAgentTrajectoryBatchPromotionPreviewResponse | null>(null);
	const [expandedReplayDetails, setExpandedReplayDetails] = useState(false);
	const [expandedPromotionDetails, setExpandedPromotionDetails] =
		useState(false);
	const [expandedBatchDetails, setExpandedBatchDetails] = useState(false);

	useEffect(() => {
		if (singleResultTurnId === selectedTurnId) return;
		setSingleResultTurnId(selectedTurnId);
		setReplayResult(null);
		setPromotionResult(null);
		setError(null);
		setExpandedReplayDetails(false);
		setExpandedPromotionDetails(false);
	}, [selectedTurnId, singleResultTurnId]);

	useEffect(() => {
		if (batchResultTurnIdsKey === batchTurnIdsKey) return;
		setBatchResultTurnIdsKey(batchTurnIdsKey);
		setBatchReplayResult(null);
		setBatchPromotionResult(null);
		setExpandedBatchDetails(false);
	}, [batchResultTurnIdsKey, batchTurnIdsKey]);

	const getActionRequest = () =>
		buildTrajectoryActionRequest({
			answerSubstringChars,
			caseIdPrefix,
			copyAnswerSubstring,
			copyToolTrajectory,
		});

	async function handleReplay() {
		if (!selected) return;
		setRunningAction("replay");
		setError(null);
		try {
			const result = await client.replayTrajectoryTurn(
				selected.id,
				getActionRequest(),
			);
			setSingleResultTurnId(selected.id);
			setReplayResult(result);
			setExpandedReplayDetails(false);
		} catch (nextError) {
			setError(
				nextError instanceof Error
					? nextError.message
					: "Failed to replay trajectory turn.",
			);
		} finally {
			setRunningAction(null);
		}
	}

	async function handlePromote() {
		if (!selected) return;
		setRunningAction("promote");
		setError(null);
		try {
			const result = await client.promoteTrajectoryTurn(
				selected.id,
				getActionRequest(),
			);
			setSingleResultTurnId(selected.id);
			setPromotionResult(result);
			setExpandedPromotionDetails(false);
		} catch (nextError) {
			setError(
				nextError instanceof Error
					? nextError.message
					: "Failed to promote trajectory turn.",
			);
		} finally {
			setRunningAction(null);
		}
	}

	async function handleBatchReplayCompare() {
		if (!hasBatchSelection) return;
		setRunningAction("batchReplay");
		setError(null);
		try {
			const result = await client.batchReplayCompareTrajectoryTurns({
				turn_ids: batchTurnIds,
				...getActionRequest(),
			});
			setBatchResultTurnIdsKey(batchTurnIdsKey);
			setBatchReplayResult(result);
			setBatchPromotionResult(null);
			setExpandedBatchDetails(false);
		} catch (nextError) {
			setError(
				nextError instanceof Error
					? nextError.message
					: "Failed to compare trajectory turns.",
			);
		} finally {
			setRunningAction(null);
		}
	}

	async function handleBatchPromotePreview() {
		if (!hasBatchSelection) return;
		setRunningAction("batchPromote");
		setError(null);
		try {
			const result = await client.batchPromoteTrajectoryTurnsPreview({
				turn_ids: batchTurnIds,
				...getActionRequest(),
			});
			setBatchResultTurnIdsKey(batchTurnIdsKey);
			setBatchPromotionResult(result);
			setBatchReplayResult(null);
			setExpandedBatchDetails(false);
		} catch (nextError) {
			setError(
				nextError instanceof Error
					? nextError.message
					: "Failed to preview trajectory promotion batch.",
			);
		} finally {
			setRunningAction(null);
		}
	}

	const hasCurrentSingleResult = singleResultTurnId === selectedTurnId;
	const hasCurrentBatchResult = batchResultTurnIdsKey === batchTurnIdsKey;

	return {
		answerSubstringChars,
		batchPromotionResult: hasCurrentBatchResult
			? rawBatchPromotionResult
			: null,
		batchReplayResult: hasCurrentBatchResult ? rawBatchReplayResult : null,
		caseIdPrefix,
		copyAnswerSubstring,
		copyToolTrajectory,
		error,
		expandedBatchDetails,
		expandedPromotionDetails,
		expandedReplayDetails,
		handleBatchPromotePreview,
		handleBatchReplayCompare,
		handlePromote,
		handleReplay,
		promotionResult: hasCurrentSingleResult ? rawPromotionResult : null,
		replayResult: hasCurrentSingleResult ? rawReplayResult : null,
		runningAction,
		setAnswerSubstringChars,
		setCaseIdPrefix,
		setCopyAnswerSubstring,
		setCopyToolTrajectory,
		setExpandedBatchDetails,
		setExpandedPromotionDetails,
		setExpandedReplayDetails,
	};
}
