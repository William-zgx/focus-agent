import {
  type FocusEvent,
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

export type ShellTooltipState = {
  text: string;
  anchorBottom: number;
  anchorCenterX: number;
  anchorTop: number;
  left: number;
  top: number;
};

export function useShellTooltipState() {
  const [tooltipState, setTooltipState] = useState<ShellTooltipState | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const closestTooltipTarget = useCallback((target: EventTarget | null) => {
    if (!(target instanceof Element)) {
      return null;
    }
    const tooltipTarget = target.closest("[data-tooltip]");
    return tooltipTarget instanceof HTMLElement ? tooltipTarget : null;
  }, []);

  const updateTooltipForElement = useCallback((element: HTMLElement) => {
    const tooltip = element.dataset.tooltip?.trim();
    if (!tooltip) {
      setTooltipState(null);
      return;
    }
    const rect = element.getBoundingClientRect();
    const margin = 12;
    const gap = 10;
    const width = Math.min(240, window.innerWidth - 24);
    const left = Math.max(
      margin,
      Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - margin),
    );
    const estimatedHeight = 44;
    const top =
      rect.top - gap - estimatedHeight >= margin
        ? rect.top - gap - estimatedHeight
        : Math.min(window.innerHeight - estimatedHeight - margin, rect.bottom + gap);
    setTooltipState({
      anchorBottom: rect.bottom,
      anchorCenterX: rect.left + rect.width / 2,
      anchorTop: rect.top,
      text: tooltip,
      left,
      top,
    });
  }, []);

  const handleTooltipShow = useCallback(
    (event: ReactMouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => {
      const currentTarget = event.currentTarget;
      if (currentTarget instanceof HTMLElement) {
        updateTooltipForElement(currentTarget);
      }
    },
    [updateTooltipForElement],
  );

  const handleTooltipHide = useCallback(() => {
    setTooltipState(null);
  }, []);

  const handleMouseOver = useCallback(
    (event: globalThis.MouseEvent) => {
      const element = closestTooltipTarget(event.target);
      if (!element) return;
      updateTooltipForElement(element);
    },
    [closestTooltipTarget, updateTooltipForElement],
  );

  const handleFocusIn = useCallback(
    (event: globalThis.FocusEvent) => {
      const element = closestTooltipTarget(event.target);
      if (!element) return;
      updateTooltipForElement(element);
    },
    [closestTooltipTarget, updateTooltipForElement],
  );

  const handleMouseOut = useCallback(
    (event: globalThis.MouseEvent) => {
      const nextTarget = event.relatedTarget;
      if (closestTooltipTarget(nextTarget)) return;
      setTooltipState(null);
    },
    [closestTooltipTarget],
  );

  const handleFocusOut = useCallback(
    (event: globalThis.FocusEvent) => {
      const nextTarget = event.relatedTarget;
      if (closestTooltipTarget(nextTarget)) return;
      setTooltipState(null);
    },
    [closestTooltipTarget],
  );

  const clearOnViewportChange = useCallback(() => {
    setTooltipState(null);
  }, []);

  useEffect(() => {
    document.addEventListener("mouseover", handleMouseOver);
    document.addEventListener("focusin", handleFocusIn);
    document.addEventListener("mouseout", handleMouseOut);
    document.addEventListener("focusout", handleFocusOut);
    window.addEventListener("scroll", clearOnViewportChange, true);
    window.addEventListener("resize", clearOnViewportChange);

    return () => {
      document.removeEventListener("mouseover", handleMouseOver);
      document.removeEventListener("focusin", handleFocusIn);
      document.removeEventListener("mouseout", handleMouseOut);
      document.removeEventListener("focusout", handleFocusOut);
      window.removeEventListener("scroll", clearOnViewportChange, true);
      window.removeEventListener("resize", clearOnViewportChange);
    };
  }, [
    handleMouseOver,
    handleFocusIn,
    handleMouseOut,
    handleFocusOut,
    clearOnViewportChange,
  ]);

  useLayoutEffect(() => {
    const tooltipElement = tooltipRef.current;
    if (!tooltipState || !tooltipElement) return;

    const margin = 12;
    const gap = 10;
    const rect = tooltipElement.getBoundingClientRect();
    const nextLeft = Math.max(
      margin,
      Math.min(
        tooltipState.anchorCenterX - rect.width / 2,
        window.innerWidth - rect.width - margin,
      ),
    );
    const canPlaceAbove = tooltipState.anchorTop - gap - rect.height >= margin;
    const nextTop = canPlaceAbove
      ? tooltipState.anchorTop - rect.height - gap
      : Math.min(window.innerHeight - rect.height - margin, tooltipState.anchorBottom + gap);

    if (
      Math.abs(nextLeft - tooltipState.left) < 0.5 &&
      Math.abs(nextTop - tooltipState.top) < 0.5
    ) {
      return;
    }

    setTooltipState((current) =>
      current
        ? {
            ...current,
            left: nextLeft,
            top: nextTop,
          }
        : current,
    );
  }, [tooltipState]);

  const tooltipProps = {
    tooltipRef,
    tooltipState,
    onShow: handleTooltipShow,
    onHide: handleTooltipHide,
  } as const;

  return tooltipProps;
}
