import type { BranchTreeNode } from "@focus-agent/web-sdk";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
	BRANCH_DETAIL_HEIGHT_ESTIMATE,
	BRANCH_DETAIL_HIDE_DELAY_MS,
	BRANCH_DETAIL_WIDTH,
	findNode,
} from "@/features/branch-tree/branch-tree-helpers";

type UseBranchDetailOverlayStateOptions = {
	root?: BranchTreeNode | null;
};

export function useBranchDetailOverlayState({
	root,
}: UseBranchDetailOverlayStateOptions) {
	const [detailThreadId, setDetailThreadId] = useState<string>("");
	const [detailStyle, setDetailStyle] = useState<CSSProperties>({});
	const detailAnchorRef = useRef<HTMLElement | null>(null);
	const detailOverlayRef = useRef<HTMLDivElement | null>(null);
	const detailHideTimerRef = useRef<number | null>(null);

	const detailNode = useMemo(
		() => findNode(root ?? undefined, detailThreadId) ?? null,
		[detailThreadId, root],
	);
	const detailDepth = detailNode ? Number(detailNode.branch_depth || 0) : 0;

	const getBranchDetailStyle = useCallback(
		(anchor: HTMLElement): CSSProperties => {
			const rect = anchor.getBoundingClientRect();
			const scrollFrame =
				anchor.closest<HTMLElement>(".fa-sidebar-scroll") ??
				anchor.closest<HTMLElement>(".fa-sidebar-panel");
			const overlayWidth = Math.min(
				BRANCH_DETAIL_WIDTH,
				window.innerWidth - 32,
			);
			const overlayHeight =
				detailOverlayRef.current?.getBoundingClientRect().height ||
				BRANCH_DETAIL_HEIGHT_ESTIMATE;
			const margin = 16;
			const gap = 16;
			const scrollbarGutter = scrollFrame ? 18 : 0;
			const horizontalMin = scrollFrame
				? Math.max(margin, scrollFrame.getBoundingClientRect().left + margin)
				: margin;
			const horizontalMax = scrollFrame
				? Math.min(
						window.innerWidth - margin,
						scrollFrame.getBoundingClientRect().right -
							margin -
							scrollbarGutter,
					)
				: window.innerWidth - margin;
			const preferredRight = rect.right + gap;
			const preferredLeft = rect.left - gap - overlayWidth;
			let left = preferredRight;

			if (
				preferredRight + overlayWidth > horizontalMax &&
				preferredLeft >= horizontalMin
			) {
				left = preferredLeft;
			}

			left = Math.min(
				Math.max(horizontalMin, left),
				Math.max(horizontalMin, horizontalMax - overlayWidth),
			);
			const placedBesideAnchor =
				(left >= preferredRight - 1 && left <= preferredRight + 1) ||
				(left >= preferredLeft - 1 && left <= preferredLeft + 1);
			const centeredTop = rect.top + rect.height / 2 - overlayHeight / 2;
			const belowTop = rect.bottom + gap;
			const aboveTop = rect.top - gap - overlayHeight;
			let top = placedBesideAnchor
				? centeredTop
				: belowTop + overlayHeight <= window.innerHeight - margin ||
						aboveTop < margin
					? belowTop
					: aboveTop;

			top = Math.min(
				Math.max(margin, top),
				Math.max(margin, window.innerHeight - overlayHeight - margin),
			);

			return {
				left: `${left}px`,
				top: `${top}px`,
			};
		},
		[],
	);

	const updateBranchDetailPosition = useCallback(() => {
		const anchor = detailAnchorRef.current;
		if (!anchor) return;
		setDetailStyle(getBranchDetailStyle(anchor));
	}, [getBranchDetailStyle]);

	const clearBranchDetailHideTimer = useCallback(() => {
		if (detailHideTimerRef.current == null) return;
		window.clearTimeout(detailHideTimerRef.current);
		detailHideTimerRef.current = null;
	}, []);

	const hideBranchDetail = useCallback(() => {
		clearBranchDetailHideTimer();
		detailAnchorRef.current = null;
		setDetailThreadId("");
		setDetailStyle({});
	}, [clearBranchDetailHideTimer]);

	const scheduleHideBranchDetail = useCallback(() => {
		clearBranchDetailHideTimer();
		detailHideTimerRef.current = window.setTimeout(() => {
			detailHideTimerRef.current = null;
			hideBranchDetail();
		}, BRANCH_DETAIL_HIDE_DELAY_MS);
	}, [clearBranchDetailHideTimer, hideBranchDetail]);

	const showBranchDetail = useCallback(
		(node: BranchTreeNode, anchorElement: HTMLElement | null) => {
			if (!anchorElement) return;
			clearBranchDetailHideTimer();
			const nextStyle = getBranchDetailStyle(anchorElement);
			const isSameAnchor = detailAnchorRef.current === anchorElement;
			detailAnchorRef.current = anchorElement;
			setDetailStyle(nextStyle);
			setDetailThreadId((current) =>
				current === node.thread_id ? current : node.thread_id,
			);
			if (!isSameAnchor) {
				updateBranchDetailPosition();
			}
		},
		[
			clearBranchDetailHideTimer,
			getBranchDetailStyle,
			updateBranchDetailPosition,
		],
	);

	useEffect(() => {
		if (!detailThreadId) return;

		function handleViewportChange() {
			updateBranchDetailPosition();
		}

		window.addEventListener("scroll", handleViewportChange, true);
		window.addEventListener("resize", handleViewportChange);
		return () => {
			window.removeEventListener("scroll", handleViewportChange, true);
			window.removeEventListener("resize", handleViewportChange);
		};
	}, [detailThreadId, updateBranchDetailPosition]);

	useEffect(() => {
		if (detailThreadId && !detailNode) {
			hideBranchDetail();
		}
	}, [detailNode, detailThreadId, hideBranchDetail]);

	useEffect(
		() => () => clearBranchDetailHideTimer(),
		[clearBranchDetailHideTimer],
	);

	return {
		clearBranchDetailHideTimer,
		detailAnchorRef,
		detailDepth,
		detailNode,
		detailOverlayRef,
		detailStyle,
		detailThreadId,
		hideBranchDetail,
		scheduleHideBranchDetail,
		showBranchDetail,
		updateBranchDetailPosition,
	};
}
