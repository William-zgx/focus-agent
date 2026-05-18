import {
	type KeyboardEvent,
	type PointerEvent as ReactPointerEvent,
	useEffect,
	useRef,
	useState,
} from "react";

import {
	clampSidebarWidth,
	getSidebarViewportMax,
	SIDEBAR_WIDTH_MIN,
} from "@/app/shell/app-shell-config";

export function useShellResizer(options: {
	sidebarCollapsed: boolean;
	sidebarWidth: number;
	setSidebarWidth: (updater: (current: number) => number) => void;
}) {
	const { sidebarCollapsed, sidebarWidth, setSidebarWidth } = options;
	const [isResizing, setIsResizing] = useState(false);
	const resizeSessionRef = useRef<{
		pointerId: number;
		startX: number;
		startWidth: number;
	} | null>(null);

	useEffect(() => {
		if (!isResizing) return;
		document.body.classList.add("fa-is-resizing");

		function handlePointerMove(event: PointerEvent) {
			const session = resizeSessionRef.current;
			if (!session || event.pointerId !== session.pointerId) return;
			const next = session.startWidth + (event.clientX - session.startX);
			setSidebarWidth(() => clampSidebarWidth(next));
		}

		function handlePointerUp(event: PointerEvent) {
			const session = resizeSessionRef.current;
			if (!session || event.pointerId !== session.pointerId) return;
			resizeSessionRef.current = null;
			setIsResizing(false);
		}

		window.addEventListener("pointermove", handlePointerMove);
		window.addEventListener("pointerup", handlePointerUp);
		window.addEventListener("pointercancel", handlePointerUp);

		return () => {
			document.body.classList.remove("fa-is-resizing");
			window.removeEventListener("pointermove", handlePointerMove);
			window.removeEventListener("pointerup", handlePointerUp);
			window.removeEventListener("pointercancel", handlePointerUp);
		};
	}, [isResizing, setSidebarWidth]);

	function handleResizerPointerDown(event: ReactPointerEvent<HTMLHRElement>) {
		if (sidebarCollapsed) return;
		resizeSessionRef.current = {
			pointerId: event.pointerId,
			startX: event.clientX,
			startWidth: sidebarWidth,
		};
		setIsResizing(true);
		event.currentTarget.setPointerCapture?.(event.pointerId);
		event.preventDefault();
	}

	function handleResizerKeyDown(event: KeyboardEvent<HTMLHRElement>) {
		if (event.key === "ArrowLeft") {
			event.preventDefault();
			setSidebarWidth((value) => clampSidebarWidth(value - 16));
			return;
		}
		if (event.key === "ArrowRight") {
			event.preventDefault();
			setSidebarWidth((value) => clampSidebarWidth(value + 16));
			return;
		}
		if (event.key === "Home") {
			event.preventDefault();
			setSidebarWidth(() => SIDEBAR_WIDTH_MIN);
			return;
		}
		if (event.key === "End") {
			event.preventDefault();
			setSidebarWidth(() => getSidebarViewportMax());
		}
	}

	return {
		isResizing,
		handleResizerPointerDown,
		handleResizerKeyDown,
	};
}
