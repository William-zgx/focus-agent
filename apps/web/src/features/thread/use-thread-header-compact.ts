import { type DependencyList, type RefObject, useLayoutEffect } from "react";

import { syncTooltipText } from "@/shared/ui/tooltip";

function buttonLabelIsTruncated(button: HTMLElement) {
	const label = button.querySelector(".fa-toolbar-text");
	if (!(label instanceof HTMLElement)) {
		return false;
	}
	return label.scrollWidth > label.clientWidth + 2;
}

function visibleElementWidth(element: Element | null) {
	if (!(element instanceof HTMLElement) || element.hidden) {
		return 0;
	}
	return Math.ceil(
		Math.max(element.scrollWidth, element.getBoundingClientRect().width),
	);
}

function actionGroupsNeedCompact(actions: HTMLElement) {
	const groups = Array.from(actions.children).filter(
		(child) => child instanceof HTMLElement && !child.hidden,
	);
	if (!groups.length) {
		return false;
	}
	const styles = window.getComputedStyle(actions);
	const gap = Number.parseFloat(styles.columnGap || styles.gap || "0") || 0;
	const requiredWidth =
		groups.reduce((total, group) => total + visibleElementWidth(group), 0) +
		gap * Math.max(0, groups.length - 1);
	return requiredWidth > actions.clientWidth + 2;
}

function compactButtonsAreClipped(
	actions: HTMLElement,
	compactButtons: HTMLElement[],
) {
	const actionsRect = actions.getBoundingClientRect();
	return compactButtons.some((button) => {
		const rect = button.getBoundingClientRect();
		return (
			rect.left < actionsRect.left - 1 || rect.right > actionsRect.right + 1
		);
	});
}

function getCompactButtons(container: HTMLElement) {
	return Array.from(
		container.querySelectorAll('[data-compact-button="true"]'),
	).filter((button): button is HTMLElement => button instanceof HTMLElement);
}

export function useThreadHeaderCompact(
	actionsRef: RefObject<HTMLDivElement | null>,
	dependencies: DependencyList,
) {
	useLayoutEffect(() => {
		let frameId = 0;

		function recomputeCompact() {
			const container = actionsRef.current;
			if (!container) return;
			const compactButtons = getCompactButtons(container);
			container.classList.remove("is-compact");
			for (const button of compactButtons) {
				syncTooltipText(button, button.dataset.defaultTooltip);
			}
			const hasTruncatedLabel = compactButtons.some((button) =>
				buttonLabelIsTruncated(button),
			);
			const shouldHideLabel =
				actionGroupsNeedCompact(container) ||
				compactButtonsAreClipped(container, compactButtons) ||
				hasTruncatedLabel;
			container.classList.toggle("is-compact", shouldHideLabel);
			for (const button of compactButtons) {
				const tooltip =
					button.dataset.fullLabel || button.getAttribute("aria-label") || "";
				if (shouldHideLabel && tooltip) {
					syncTooltipText(button, tooltip);
				} else if (button.dataset.defaultTooltip || button.title) {
					syncTooltipText(button, button.dataset.defaultTooltip);
				} else {
					syncTooltipText(button, undefined);
				}
			}
		}

		function scheduleRecomputeCompact() {
			window.cancelAnimationFrame(frameId);
			frameId = window.requestAnimationFrame(() => {
				recomputeCompact();
			});
		}

		const container = actionsRef.current;
		if (!container) return;
		const header = container.closest(".fa-chat-header-top");

		scheduleRecomputeCompact();
		const observer = new ResizeObserver(() => {
			scheduleRecomputeCompact();
		});
		observer.observe(container);
		if (header instanceof HTMLElement) {
			observer.observe(header);
		}
		const mutationObserver = new MutationObserver(() => {
			scheduleRecomputeCompact();
		});
		mutationObserver.observe(container, {
			childList: true,
			subtree: true,
			characterData: true,
			attributes: true,
			attributeFilter: ["hidden", "class", "style", "data-full-label"],
		});
		window.addEventListener("resize", scheduleRecomputeCompact);
		document.fonts?.ready?.then(() => {
			scheduleRecomputeCompact();
		});
		return () => {
			observer.disconnect();
			mutationObserver.disconnect();
			window.cancelAnimationFrame(frameId);
			window.removeEventListener("resize", scheduleRecomputeCompact);
		};
		// This hook intentionally mirrors the caller's layout-sensitive inputs.
	}, [actionsRef, ...dependencies]);
}
