import { useCallback, useEffect, useRef, useState } from "react";

const BRANCH_ZOOM_MIN = 0.5;
const BRANCH_ZOOM_MAX = 1.8;
const BRANCH_ZOOM_WHEEL_SENSITIVITY = 0.0015;

type WebKitGestureEvent = Event & {
  scale?: number;
};

type PositionedNode = {
  x: number;
  y: number;
};

type UseBranchTreeViewportOptions = {
  graphDependency: unknown;
  nodeIndex: Map<string, PositionedNode>;
  onDetailPositionUpdate: () => void;
  selectedThreadId: string;
};

export function clampBranchZoom(value: number) {
  return Math.min(BRANCH_ZOOM_MAX, Math.max(BRANCH_ZOOM_MIN, Number(value.toFixed(2))));
}

export function branchZoomLabel(value: number) {
  return `${Math.round(value * 100)}%`;
}

export { BRANCH_ZOOM_MAX, BRANCH_ZOOM_MIN };

export function useBranchTreeViewport({
  graphDependency,
  nodeIndex,
  onDetailPositionUpdate,
  selectedThreadId,
}: UseBranchTreeViewportOptions) {
  const [branchZoom, setBranchZoom] = useState(1);
  const [viewportNudge, setViewportNudge] = useState({
    x: 0,
    y: 0,
  });
  const treeCanvasRef = useRef<HTMLDivElement | null>(null);
  const branchZoomRef = useRef(1);
  const gestureStartZoomRef = useRef(1);
  const pendingZoomCenterBehaviorRef = useRef<ScrollBehavior | null>(null);
  const canvasAutoCenteringRef = useRef(false);

  branchZoomRef.current = branchZoom;

  const readCanvasInsets = useCallback(() => {
    const canvas = treeCanvasRef.current;
    if (!canvas || typeof window === "undefined") return { x: 0, y: 0 };
    const styles = window.getComputedStyle(canvas);
    return {
      x: Number.parseFloat(styles.paddingLeft) || 0,
      y: Number.parseFloat(styles.paddingTop) || 0,
    };
  }, []);

  const centerSelectedNode = useCallback(
    (zoom = branchZoomRef.current, behavior: ScrollBehavior = "smooth") => {
      const canvas = treeCanvasRef.current;
      const node = nodeIndex.get(selectedThreadId);
      if (!canvas || !node) return;

      const canvasInsets = readCanvasInsets();
      const nodeCenterX = canvasInsets.x + node.x * zoom;
      const nodeCenterY = canvasInsets.y + node.y * zoom;
      const maxScrollLeft = Math.max(0, canvas.scrollWidth - canvas.clientWidth);
      const maxScrollTop = Math.max(0, canvas.scrollHeight - canvas.clientHeight);
      const desiredLeft = nodeCenterX - canvas.clientWidth / 2;
      const desiredTop = nodeCenterY - canvas.clientHeight / 2;
      const left = Math.min(Math.max(0, desiredLeft), maxScrollLeft);
      const top = Math.min(Math.max(0, desiredTop), maxScrollTop);

      canvasAutoCenteringRef.current = true;
      setViewportNudge({
        x: Math.round(left - desiredLeft),
        y: Math.round(top - desiredTop),
      });
      canvas.scrollTo({ left, top, behavior });
      window.requestAnimationFrame(() => {
        canvasAutoCenteringRef.current = false;
      });
    },
    [nodeIndex, readCanvasInsets, selectedThreadId],
  );

  const updateBranchZoom = useCallback((nextZoom: number, behavior: ScrollBehavior = "auto") => {
    const zoom = clampBranchZoom(nextZoom);
    branchZoomRef.current = zoom;
    pendingZoomCenterBehaviorRef.current = behavior;
    setBranchZoom((current) => (Math.abs(current - zoom) < 0.001 ? current : zoom));
  }, []);

  useEffect(() => {
    const canvas = treeCanvasRef.current;
    if (!canvas) return;

    function handleScroll() {
      if (canvasAutoCenteringRef.current) return;
      setViewportNudge((current) => (current.x === 0 && current.y === 0 ? current : { x: 0, y: 0 }));
    }

    canvas.addEventListener("scroll", handleScroll, { passive: true });
    return () => canvas.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    setViewportNudge({ x: 0, y: 0 });
  }, [selectedThreadId]);

  useEffect(() => {
    const behavior = pendingZoomCenterBehaviorRef.current;
    if (!behavior) return;
    pendingZoomCenterBehaviorRef.current = null;
    const frame = window.requestAnimationFrame(() => {
      centerSelectedNode(branchZoom, behavior);
      onDetailPositionUpdate();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [branchZoom, centerSelectedNode, onDetailPositionUpdate]);

  useEffect(() => {
    const canvas = treeCanvasRef.current;
    if (!canvas) return;

    function handleWheel(event: WheelEvent) {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const nextZoom = branchZoomRef.current * Math.exp(-event.deltaY * BRANCH_ZOOM_WHEEL_SENSITIVITY);
      updateBranchZoom(nextZoom, "auto");
    }

    const handleGestureStart: EventListener = (event) => {
      event.preventDefault();
      gestureStartZoomRef.current = branchZoomRef.current;
    };

    const handleGestureChange: EventListener = (event) => {
      event.preventDefault();
      const scale = (event as WebKitGestureEvent).scale ?? 1;
      updateBranchZoom(gestureStartZoomRef.current * scale, "auto");
    };

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    canvas.addEventListener("gesturestart", handleGestureStart, { passive: false } as AddEventListenerOptions);
    canvas.addEventListener("gesturechange", handleGestureChange, { passive: false } as AddEventListenerOptions);

    return () => {
      canvas.removeEventListener("wheel", handleWheel);
      canvas.removeEventListener("gesturestart", handleGestureStart);
      canvas.removeEventListener("gesturechange", handleGestureChange);
    };
  }, [graphDependency, selectedThreadId, updateBranchZoom]);

  return {
    branchZoom,
    branchZoomRef,
    centerSelectedNode,
    treeCanvasRef,
    updateBranchZoom,
    viewportNudge,
  };
}
