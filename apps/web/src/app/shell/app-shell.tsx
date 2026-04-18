import {
  type CSSProperties,
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type PropsWithChildren,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";

import { BranchTreePanel } from "@/features/branch-tree/branch-tree-panel";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";
import { ConversationToolbar } from "@/features/conversations/conversation-toolbar";
import { MergeReviewCard } from "@/features/merge-review/merge-review-card";
import { ThreadHeaderActions } from "@/features/thread/thread-header-actions";
import { useThreadState } from "@/features/thread/use-thread-state";
import {
  type ColorPreference,
  type LanguagePreference,
  ShellUiProvider,
  type ThemePreference,
  useTransientShellStatus,
} from "@/app/shell/shell-ui-context";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import { FocusAgentBrand } from "@/shared/ui/focus-agent-brand";
import { tooltipProps } from "@/shared/ui/tooltip";

const SIDEBAR_COLLAPSED_KEY = "fa:sidebar-collapsed";
const SIDEBAR_WIDTH_KEY = "fa:sidebar-width";
const LANGUAGE_KEY = "fa:language";
const THEME_KEY = "fa:theme";
const COLOR_KEY = "fa:color";
const DEFAULT_LANGUAGE_PREFERENCE: LanguagePreference = "zh";
const DEFAULT_THEME_PREFERENCE: ThemePreference = "system";
const DEFAULT_COLOR_PREFERENCE: ColorPreference = "white";
const SIDEBAR_WIDTH_DEFAULT = 300;
const SIDEBAR_WIDTH_MIN = 260;
const SIDEBAR_DEFAULT_RATIO = 1 / 3;
const SIDEBAR_MAX_RATIO = 1 / 2;
const SHELL_PADDING_DESKTOP = 18;
const SHELL_PADDING_MOBILE = 12;
const RESIZER_WIDTH_DESKTOP = 16;
const RESIZER_WIDTH_TABLET = 12;
const LANGUAGE_OPTIONS = [
  { value: "zh", shortLabel: "中", labelZh: "中文", labelEn: "Chinese" },
  { value: "en", shortLabel: "EN", labelZh: "英文", labelEn: "English" },
] as const;
const THEME_OPTIONS = [
  { value: "system", labelZh: "跟随系统", labelEn: "Follow system" },
  { value: "light", labelZh: "浅色", labelEn: "Light" },
  { value: "dark", labelZh: "深色", labelEn: "Dark" },
] as const;
const COLOR_OPTIONS = [
  { value: "white", labelZh: "白色", labelEn: "White" },
  { value: "blue", labelZh: "蓝色", labelEn: "Blue" },
  { value: "mint", labelZh: "薄荷", labelEn: "Mint" },
  { value: "sunset", labelZh: "暮光", labelEn: "Sunset" },
  { value: "graphite", labelZh: "石墨", labelEn: "Graphite" },
] as const;

function getSidebarAvailableWidth() {
  if (typeof window === "undefined") {
    return SIDEBAR_WIDTH_DEFAULT;
  }

  if (window.innerWidth <= 900) {
    return SIDEBAR_WIDTH_MIN;
  }

  const shellPadding = window.innerWidth <= 900 ? SHELL_PADDING_MOBILE : SHELL_PADDING_DESKTOP;
  const resizerWidth = window.innerWidth <= 1280 ? RESIZER_WIDTH_TABLET : RESIZER_WIDTH_DESKTOP;
  return Math.max(SIDEBAR_WIDTH_MIN, window.innerWidth - shellPadding * 2 - resizerWidth);
}

function getSidebarViewportMax() {
  if (typeof window === "undefined") {
    return SIDEBAR_WIDTH_DEFAULT;
  }

  if (window.innerWidth <= 900) {
    return SIDEBAR_WIDTH_MIN;
  }

  return Math.max(
    SIDEBAR_WIDTH_MIN,
    Math.floor(getSidebarAvailableWidth() * SIDEBAR_MAX_RATIO),
  );
}

function clampSidebarWidth(value: number) {
  const viewportMax = getSidebarViewportMax();
  return Math.max(SIDEBAR_WIDTH_MIN, Math.min(viewportMax, Math.round(value)));
}

function getSidebarDefaultWidth() {
  if (typeof window === "undefined") {
    return SIDEBAR_WIDTH_DEFAULT;
  }

  if (window.innerWidth <= 900) {
    return SIDEBAR_WIDTH_MIN;
  }

  return clampSidebarWidth(Math.floor(getSidebarAvailableWidth() * SIDEBAR_DEFAULT_RATIO));
}

function renderThemeIcon(value: ThemePreference) {
  if (value === "light") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="10" cy="10" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.45" />
        <path
          d="M10 2.9v2M10 15.1v2M17.1 10h-2M5.1 10h-2M15 5l-1.4 1.4M6.4 13.6 5 15M15 15l-1.4-1.4M6.4 6.4 5 5"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeWidth="1.45"
        />
      </svg>
    );
  }

  if (value === "dark") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path
          d="M11.2 3.2a6.2 6.2 0 1 0 5.6 8.8 5.1 5.1 0 0 1-5.6-8.8Z"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.45"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect
        x="4.3"
        y="4.6"
        width="11.4"
        height="8"
        rx="1.7"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.35"
      />
      <path
        d="M7.4 15.4h5.2M10 12.6v2.8"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.35"
      />
    </svg>
  );
}

function cycleOptionValue<T extends string>(
  current: T,
  options: readonly { value: T }[],
) {
  const currentIndex = options.findIndex((option) => option.value === current);
  const nextIndex = currentIndex === -1 ? 0 : (currentIndex + 1) % options.length;
  return options[nextIndex].value;
}

export function AppShell({ children }: PropsWithChildren) {
  const { principal } = useFocusAgent();
  const navigate = useNavigate();
  const { conversationId, threadId, isReviewRoute } = useRouterState({
    select: (state) => {
      const routeParams = (state.matches.at(-1)?.params ?? {}) as Partial<
        Record<"conversationId" | "threadId", string>
      >;
      return {
        conversationId: String(routeParams.conversationId ?? ""),
        threadId: String(routeParams.threadId ?? ""),
        isReviewRoute: state.location.pathname.endsWith("/review"),
      };
    },
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => getSidebarDefaultWidth());
  const [isResizing, setIsResizing] = useState(false);
  const [languagePreference, setLanguagePreference] = useState<LanguagePreference>(
    DEFAULT_LANGUAGE_PREFERENCE,
  );
  const [themePreference, setThemePreference] = useState<ThemePreference>(
    DEFAULT_THEME_PREFERENCE,
  );
  const [colorPreference, setColorPreference] = useState<ColorPreference>(
    DEFAULT_COLOR_PREFERENCE,
  );
  const [branchCreateBusy, setBranchCreateBusy] = useState(false);
  const [shellStatus, setShellStatus] = useTransientShellStatus();
  const [tooltipState, setTooltipState] = useState<{
    text: string;
    anchorBottom: number;
    anchorCenterX: number;
    anchorTop: number;
    left: number;
    top: number;
  } | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const resizeSessionRef = useRef<{
    pointerId: number;
    startX: number;
    startWidth: number;
  } | null>(null);
  const { data: activeThreadState } = useThreadState(threadId);
  const { forkBranch } = useBranchActions({
    rootThreadId: conversationId,
    threadId,
  });
  const isChineseUi = languagePreference === "zh";

  useEffect(() => {
    const urlLanguage = new URLSearchParams(window.location.search).get("lang");
    if (urlLanguage === "en" || urlLanguage === "zh") {
      setLanguagePreference(urlLanguage);
    }
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (stored === "1") {
      setSidebarCollapsed(true);
    }
    const rawWidth = Number.parseInt(window.localStorage.getItem(SIDEBAR_WIDTH_KEY) ?? "", 10);
    if (Number.isFinite(rawWidth)) {
      setSidebarWidth(clampSidebarWidth(rawWidth));
    } else {
      setSidebarWidth(getSidebarDefaultWidth());
    }
    const savedLanguage =
      urlLanguage === "en" || urlLanguage === "zh"
        ? urlLanguage
        : window.localStorage.getItem(LANGUAGE_KEY);
    if (savedLanguage === "en" || savedLanguage === "zh") {
      setLanguagePreference(savedLanguage);
    }
    const savedTheme = window.localStorage.getItem(THEME_KEY);
    if (savedTheme === "system" || savedTheme === "light" || savedTheme === "dark") {
      setThemePreference(savedTheme);
    }
    const savedColor = window.localStorage.getItem(COLOR_KEY);
    if (
      savedColor === "white" ||
      savedColor === "blue" ||
      savedColor === "mint" ||
      savedColor === "sunset" ||
      savedColor === "graphite"
    ) {
      setColorPreference(savedColor);
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? "1" : "0");
  }, [sidebarCollapsed]);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    function handleResize() {
      setSidebarWidth((value) => clampSidebarWidth(value));
    }

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem(LANGUAGE_KEY, languagePreference);
  }, [languagePreference]);

  useEffect(() => {
    window.localStorage.setItem(THEME_KEY, themePreference);
  }, [themePreference]);

  useEffect(() => {
    window.localStorage.setItem(COLOR_KEY, colorPreference);
  }, [colorPreference]);

  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const resolvedTheme =
      themePreference === "system" ? (media.matches ? "light" : "dark") : themePreference;
    root.dataset.theme = resolvedTheme;
    root.dataset.accent = colorPreference;
    root.lang = languagePreference === "zh" ? "zh-CN" : "en";
    document.body.dataset.uiLanguage = languagePreference;

    function handleMediaChange() {
      if (themePreference !== "system") return;
      root.dataset.theme = media.matches ? "light" : "dark";
    }

    media.addEventListener("change", handleMediaChange);
    return () => {
      media.removeEventListener("change", handleMediaChange);
    };
  }, [themePreference, colorPreference, languagePreference]);

  useEffect(() => {
    document.body.classList.toggle("has-modal", isReviewRoute);
    return () => {
      document.body.classList.remove("has-modal");
    };
  }, [isReviewRoute]);

  useEffect(() => {
    function closestTooltipTarget(target: EventTarget | null) {
      if (!(target instanceof Element)) {
        return null;
      }
      const tooltipTarget = target.closest("[data-tooltip]");
      return tooltipTarget instanceof HTMLElement ? tooltipTarget : null;
    }

    function handleMouseOver(event: MouseEvent) {
      const element = closestTooltipTarget(event.target);
      if (!element) return;
      updateTooltipForElement(element);
    }

    function handleFocusIn(event: globalThis.FocusEvent) {
      const element = closestTooltipTarget(event.target);
      if (!element) return;
      updateTooltipForElement(element);
    }

    function handleMouseOut(event: MouseEvent) {
      const nextTarget = event.relatedTarget;
      if (closestTooltipTarget(nextTarget)) return;
      setTooltipState(null);
    }

    function handleFocusOut(event: globalThis.FocusEvent) {
      const nextTarget = event.relatedTarget;
      if (closestTooltipTarget(nextTarget)) return;
      setTooltipState(null);
    }

    function handleViewportChange() {
      setTooltipState(null);
    }

    document.addEventListener("mouseover", handleMouseOver);
    document.addEventListener("focusin", handleFocusIn);
    document.addEventListener("mouseout", handleMouseOut);
    document.addEventListener("focusout", handleFocusOut);
    window.addEventListener("scroll", handleViewportChange, true);
    window.addEventListener("resize", handleViewportChange);

    return () => {
      document.removeEventListener("mouseover", handleMouseOver);
      document.removeEventListener("focusin", handleFocusIn);
      document.removeEventListener("mouseout", handleMouseOut);
      document.removeEventListener("focusout", handleFocusOut);
      window.removeEventListener("scroll", handleViewportChange, true);
      window.removeEventListener("resize", handleViewportChange);
    };
  }, []);

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

  useEffect(() => {
    if (!isReviewRoute) return;

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") return;
      void closeMergeReviewModal();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isReviewRoute]);

  useEffect(() => {
    if (!isResizing) return;
    document.body.classList.add("fa-is-resizing");

    function handlePointerMove(event: globalThis.PointerEvent) {
      const session = resizeSessionRef.current;
      if (!session || event.pointerId !== session.pointerId) return;
      const next = session.startWidth + (event.clientX - session.startX);
      setSidebarWidth(clampSidebarWidth(next));
    }

    function handlePointerUp(event: globalThis.PointerEvent) {
      const session = resizeSessionRef.current;
      if (!session || event.pointerId !== session.pointerId) return;
      resizeSessionRef.current = null;
      setIsResizing(false);
    }

    window.addEventListener("pointermove", handlePointerMove as unknown as EventListener);
    window.addEventListener("pointerup", handlePointerUp as unknown as EventListener);
    window.addEventListener("pointercancel", handlePointerUp as unknown as EventListener);

    return () => {
      document.body.classList.remove("fa-is-resizing");
      window.removeEventListener("pointermove", handlePointerMove as unknown as EventListener);
      window.removeEventListener("pointerup", handlePointerUp as unknown as EventListener);
      window.removeEventListener("pointercancel", handlePointerUp as unknown as EventListener);
    };
  }, [isResizing]);

  function toggleSidebar() {
    setSidebarCollapsed((value) => !value);
  }

  function updateTooltipForElement(element: HTMLElement) {
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
  }

  function handleTooltipShow(event: ReactMouseEvent<HTMLElement> | FocusEvent<HTMLElement>) {
    const currentTarget = event.currentTarget;
    if (currentTarget instanceof HTMLElement) {
      updateTooltipForElement(currentTarget);
    }
  }

  function handleTooltipHide() {
    setTooltipState(null);
  }

  function handleResizerPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
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

  function handleResizerKeyDown(event: KeyboardEvent<HTMLDivElement>) {
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
      setSidebarWidth(SIDEBAR_WIDTH_MIN);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setSidebarWidth(getSidebarViewportMax());
    }
  }

  const shellStyle = {
    "--fa-sidebar-width": `${sidebarWidth}px`,
  } as CSSProperties;
  const selectedLanguage =
    LANGUAGE_OPTIONS.find((option) => option.value === languagePreference) ?? LANGUAGE_OPTIONS[0];
  const selectedTheme =
    THEME_OPTIONS.find((option) => option.value === themePreference) ?? THEME_OPTIONS[0];
  const selectedColor =
    COLOR_OPTIONS.find((option) => option.value === colorPreference) ?? COLOR_OPTIONS[0];
  const selectedLanguageLabel = isChineseUi ? selectedLanguage.labelZh : selectedLanguage.labelEn;
  const selectedThemeLabel = isChineseUi ? selectedTheme.labelZh : selectedTheme.labelEn;
  const selectedColorLabel = isChineseUi ? selectedColor.labelZh : selectedColor.labelEn;

  async function createBranch(options?: { parentThreadId?: string }) {
    const parentThreadId = options?.parentThreadId ?? threadId ?? null;
    if (!conversationId || !parentThreadId || branchCreateBusy) return;
    setBranchCreateBusy(true);
    try {
      setShellStatus(
        {
          tone: "warn",
          text: languagePreference === "zh" ? "创建分支中" : "Creating branch",
        },
        { autoClearMs: 2400 },
      );
      const record = await forkBranch({
        parentThreadId,
        language: languagePreference,
      });
      await navigate({
        to: "/c/$conversationId/t/$threadId",
        params: {
          conversationId: record.root_thread_id,
          threadId: record.child_thread_id,
        },
      });
      setShellStatus(
        {
          tone: "success",
          text: languagePreference === "zh" ? "分支已创建" : "Branch created",
        },
        { autoClearMs: 2400 },
      );
    } catch (error) {
      setShellStatus(
        {
          tone: "danger",
          text:
            error instanceof Error
              ? error.message
              : languagePreference === "zh"
                ? "创建分支失败"
                : "Create branch failed",
        },
      );
    } finally {
      setBranchCreateBusy(false);
    }
  }

  async function closeMergeReviewModal() {
    if (!conversationId || !threadId) return;
    await navigate({
      to: "/c/$conversationId/t/$threadId",
      params: {
        conversationId,
        threadId,
      },
      replace: true,
    });
  }

  async function dismissModal() {
    if (isReviewRoute) {
      await closeMergeReviewModal();
    }
  }

  return (
    <ShellUiProvider
      value={{
        languagePreference,
        themePreference,
        colorPreference,
        setLanguagePreference,
        setThemePreference,
        setColorPreference,
        shellStatus,
        setShellStatus,
        createBranch,
        isCreatingBranch: branchCreateBusy,
      }}
    >
      <div
        className={`fa-app-shell ${sidebarCollapsed ? "is-sidebar-collapsed" : ""}`}
        style={shellStyle}
      >
        <aside className="fa-sidebar-panel">
          <div className="fa-sidebar-copy">
            <div className="fa-sidebar-brand">
              <div className="fa-sidebar-brand-row">
                <FocusAgentBrand />
                <div
                  className="fa-sidebar-inline-preferences"
                  aria-label={isChineseUi ? "侧栏偏好设置" : "Sidebar preferences"}
                  role="group"
                >
                  <button
                    aria-label={
                      isChineseUi
                        ? `切换语言，当前${selectedLanguageLabel}`
                        : `Switch language, current ${selectedLanguageLabel}`
                    }
                    className="fa-sidebar-preference-button fa-sidebar-language-button"
                    data-preference-group="language"
                    data-preference-value={languagePreference}
                    {...tooltipProps(
                      isChineseUi
                        ? `语言：${selectedLanguageLabel}`
                        : `Language: ${selectedLanguageLabel}`,
                    )}
                    onBlur={handleTooltipHide}
                    onClick={() =>
                      setLanguagePreference((value) => cycleOptionValue(value, LANGUAGE_OPTIONS))
                    }
                    onFocus={handleTooltipShow}
                    onMouseEnter={handleTooltipShow}
                    onMouseLeave={handleTooltipHide}
                    type="button"
                  >
                    {selectedLanguage.shortLabel}
                  </button>
                  <button
                    aria-label={
                      isChineseUi
                        ? `切换主题，当前${selectedThemeLabel}`
                        : `Switch theme, current ${selectedThemeLabel}`
                    }
                    className="fa-sidebar-preference-button"
                    data-preference-group="theme"
                    data-preference-value={themePreference}
                    {...tooltipProps(
                      isChineseUi ? `主题：${selectedThemeLabel}` : `Theme: ${selectedThemeLabel}`,
                    )}
                    onBlur={handleTooltipHide}
                    onClick={() =>
                      setThemePreference((value) => cycleOptionValue(value, THEME_OPTIONS))
                    }
                    onFocus={handleTooltipShow}
                    onMouseEnter={handleTooltipShow}
                    onMouseLeave={handleTooltipHide}
                    type="button"
                  >
                    <span className="fa-sidebar-theme-icon">{renderThemeIcon(themePreference)}</span>
                  </button>
                  <button
                    aria-label={
                      isChineseUi
                        ? `切换色系，当前${selectedColorLabel}`
                        : `Switch accent color, current ${selectedColorLabel}`
                    }
                    className="fa-sidebar-preference-button fa-sidebar-color-button"
                    data-accent-value={colorPreference}
                    data-preference-group="color"
                    {...tooltipProps(
                      isChineseUi ? `色系：${selectedColorLabel}` : `Color: ${selectedColorLabel}`,
                    )}
                    onBlur={handleTooltipHide}
                    onClick={() =>
                      setColorPreference((value) => cycleOptionValue(value, COLOR_OPTIONS))
                    }
                    onFocus={handleTooltipShow}
                    onMouseEnter={handleTooltipShow}
                    onMouseLeave={handleTooltipHide}
                    type="button"
                  >
                    <span className="fa-sidebar-color-swatch-dot" aria-hidden="true" />
                  </button>
                </div>
                <button
                  className="fa-sidebar-toggle-button"
                  {...tooltipProps(isChineseUi ? "收起侧栏" : "Collapse sidebar")}
                  onBlur={handleTooltipHide}
                  onFocus={handleTooltipShow}
                  onMouseEnter={handleTooltipShow}
                  onMouseLeave={handleTooltipHide}
                  onClick={toggleSidebar}
                  type="button"
                  aria-label={isChineseUi ? "收起侧栏" : "Collapse sidebar"}
                >
                  <svg viewBox="0 0 20 20" aria-hidden="true">
                    <rect x="4.15" y="4" width="2.2" height="12" rx="1.1" fill="currentColor" opacity="0.96" />
                    <path
                      d="M12.85 6.1 9.05 9.65a.48.48 0 0 0 0 .7l3.8 3.55c.31.29.8.07.8-.35V6.45c0-.42-.49-.64-.8-.35Z"
                      fill="currentColor"
                    />
                  </svg>
                </button>
              </div>
            </div>
          </div>
          <div className="fa-sidebar-scroll">
            <BranchTreePanel />
          </div>
        </aside>

        <div
          className="fa-panel-resizer"
          {...tooltipProps(isChineseUi ? "拖动调整左右栏宽度" : "Drag to resize panels")}
          onBlur={handleTooltipHide}
          onFocus={handleTooltipShow}
          onMouseEnter={handleTooltipShow}
          onMouseLeave={handleTooltipHide}
          onKeyDown={handleResizerKeyDown}
          onPointerDown={handleResizerPointerDown}
          role="separator"
          aria-label={isChineseUi ? "调整面板宽度" : "Resize panels"}
          aria-orientation="vertical"
          tabIndex={0}
        />

        <main className="fa-chat-panel">
          <section className="fa-header-card">
            <div className="fa-chat-header-top">
              <div className="fa-chat-header-copy">
                <button
                  className={`fa-chat-logo-toggle ${sidebarCollapsed ? "is-sidebar-collapsed" : ""}`}
                  {...tooltipProps(
                    sidebarCollapsed
                      ? isChineseUi
                        ? "展开侧栏"
                        : "Show sidebar"
                      : isChineseUi
                        ? "收起侧栏"
                        : "Collapse sidebar",
                  )}
                  onBlur={handleTooltipHide}
                  onFocus={handleTooltipShow}
                  onMouseEnter={handleTooltipShow}
                  onMouseLeave={handleTooltipHide}
                  onClick={toggleSidebar}
                  type="button"
                  aria-label={
                    sidebarCollapsed
                      ? isChineseUi
                        ? "展开侧栏"
                        : "Show sidebar"
                      : isChineseUi
                        ? "收起侧栏"
                        : "Collapse sidebar"
                  }
                >
                  <FocusAgentBrand compact />
                </button>
                <ConversationToolbar />
              </div>
              <ThreadHeaderActions onRequestOpenSidebar={() => setSidebarCollapsed(false)} />
            </div>
            {shellStatus ? (
              <div className={`fa-shell-status-line is-${shellStatus.tone}`}>{shellStatus.text}</div>
            ) : null}
          </section>

          <div className="fa-chat-main-body">{children}</div>
        </main>
      </div>

      {isReviewRoute ? (
        <button
          aria-label={isChineseUi ? "关闭弹层" : "Close dialog"}
          className="fa-modal-backdrop"
          onClick={() => void dismissModal()}
          type="button"
        />
      ) : null}

      {tooltipState ? (
        <div
          ref={tooltipRef}
          className="fa-toolbar-tooltip-overlay is-visible"
          style={{ left: `${tooltipState.left}px`, top: `${tooltipState.top}px` }}
        >
          {tooltipState.text}
        </div>
      ) : null}

      {isReviewRoute && threadId ? (
        <section className="fa-focus-modal" role="dialog" aria-modal="true" aria-labelledby="fa-merge-review-title">
          <div className="fa-focus-modal-card">
            <div className="fa-focus-modal-head">
              <div className="fa-focus-modal-copy">
                <h3 id="fa-merge-review-title">
                  {isChineseUi ? "准备合并" : "Prepare merge"}
                </h3>
                <p>
                  {isChineseUi
                    ? "检查分支总结，选择导入方式，并明确批准或拒绝上游导入。"
                    : "Review the branch summary, choose an import mode, and explicitly approve or reject the upstream import."}
                </p>
              </div>
              <button
                aria-label={isChineseUi ? "关闭合并评审弹层" : "Close merge review dialog"}
                className="fa-focus-modal-close"
                onClick={() => void closeMergeReviewModal()}
                type="button"
              >
                ×
              </button>
            </div>
            {activeThreadState?.branch_meta ? (
              <MergeReviewCard
                rootThreadId={conversationId}
                threadId={threadId}
                proposal={activeThreadState.merge_proposal}
                branchName={activeThreadState.branch_meta.branch_name}
                pendingStatus={activeThreadState.branch_meta.branch_status}
                onClose={() => void closeMergeReviewModal()}
              />
            ) : (
              <div className="fa-inline-notice is-danger">
                {isChineseUi
                  ? "合并评审只适用于分支线程。"
                  : "Merge review only applies to branch threads."}
              </div>
            )}
          </div>
        </section>
      ) : null}
    </ShellUiProvider>
  );
}
