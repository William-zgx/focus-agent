import type {
	ColorPreference,
	LanguagePreference,
	ThemePreference,
} from "@/app/shell/shell-ui-context";
import { appEnv } from "@/shared/config/env";

export const SIDEBAR_COLLAPSED_KEY = "fa:sidebar-collapsed";
export const SIDEBAR_WIDTH_KEY = "fa:sidebar-width";
export const LANGUAGE_KEY = "fa:language";
export const THEME_KEY = "fa:theme";
export const COLOR_KEY = "fa:color";

export const DEFAULT_LANGUAGE_PREFERENCE: LanguagePreference = "zh";
export const DEFAULT_THEME_PREFERENCE: ThemePreference = "system";
export const DEFAULT_COLOR_PREFERENCE: ColorPreference = "white";

export const SIDEBAR_WIDTH_DEFAULT = 300;
export const SIDEBAR_WIDTH_MIN = 260;
export const SIDEBAR_DEFAULT_RATIO = 1 / 3;
export const SIDEBAR_MAX_RATIO = 1 / 2;
export const SHELL_PADDING_DESKTOP = 18;
export const SHELL_PADDING_MOBILE = 12;
export const RESIZER_WIDTH_DESKTOP = 16;
export const RESIZER_WIDTH_TABLET = 12;

export const LANGUAGE_OPTIONS = [
	{ value: "zh", shortLabel: "中", labelZh: "中文", labelEn: "Chinese" },
	{ value: "en", shortLabel: "EN", labelZh: "英文", labelEn: "English" },
] as const;

export const THEME_OPTIONS = [
	{ value: "system", labelZh: "跟随系统", labelEn: "Follow system" },
	{ value: "light", labelZh: "浅色", labelEn: "Light" },
	{ value: "dark", labelZh: "深色", labelEn: "Dark" },
] as const;

export const COLOR_OPTIONS = [
	{ value: "white", labelZh: "白色", labelEn: "White" },
	{ value: "blue", labelZh: "蓝色", labelEn: "Blue" },
	{ value: "mint", labelZh: "薄荷", labelEn: "Mint" },
	{ value: "sunset", labelZh: "暮光", labelEn: "Sunset" },
	{ value: "graphite", labelZh: "石墨", labelEn: "Graphite" },
] as const;

export type ChatNavTarget = {
	conversationId: string;
	threadId: string;
};

export type AgentTeamNavTarget = {
	rootThreadId?: string;
	sessionId?: string;
};

export type ShellMode = "admin" | "agent-workbench" | "chat";

export function isProductivityPath(pathname: string) {
	if (!appEnv.features.productivity) return false;
	return (
		pathname === "/productivity/notes" ||
		pathname === "/productivity/tasks" ||
		pathname.startsWith("/productivity/")
	);
}

export function isAgentWorkbenchPath(pathname: string) {
	if (isProductivityPath(pathname)) return true;
	if (
		appEnv.features.agentTeam &&
		(pathname === "/agent-team" || pathname.startsWith("/agent-team/"))
	) {
		return true;
	}
	if (
		appEnv.features.observability &&
		(pathname === "/observability/overview" ||
			pathname === "/observability/trajectory")
	) {
		return true;
	}
	if (
		appEnv.features.agentGovernance &&
		(pathname === "/agent/governance" || pathname === "/agent/roles")
	) {
		return true;
	}
	return appEnv.features.agentMemory && pathname === "/agent/memory";
}

export function isAdminPath(pathname: string) {
	return (
		pathname === "/admin/users" ||
		pathname.startsWith("/admin/users/") ||
		pathname === "/admin/audit-events" ||
		pathname === "/admin/config" ||
		pathname.startsWith("/account/")
	);
}

export function resolveShellMode(pathname: string): ShellMode {
	if (pathname === "/" || pathname.startsWith("/c/")) return "chat";
	if (isAgentWorkbenchPath(pathname)) return "agent-workbench";
	if (isAdminPath(pathname)) return "admin";
	return "chat";
}

export function getSidebarAvailableWidth() {
	if (typeof window === "undefined") {
		return SIDEBAR_WIDTH_DEFAULT;
	}

	if (window.innerWidth <= 900) {
		return SIDEBAR_WIDTH_MIN;
	}

	const shellPadding =
		window.innerWidth <= 900 ? SHELL_PADDING_MOBILE : SHELL_PADDING_DESKTOP;
	const resizerWidth =
		window.innerWidth <= 1280 ? RESIZER_WIDTH_TABLET : RESIZER_WIDTH_DESKTOP;
	return Math.max(
		SIDEBAR_WIDTH_MIN,
		window.innerWidth - shellPadding * 2 - resizerWidth,
	);
}

export function getSidebarViewportMax() {
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

export function clampSidebarWidth(value: number) {
	const viewportMax = getSidebarViewportMax();
	return Math.max(SIDEBAR_WIDTH_MIN, Math.min(viewportMax, Math.round(value)));
}

export function getSidebarDefaultWidth() {
	if (typeof window === "undefined") {
		return SIDEBAR_WIDTH_DEFAULT;
	}

	if (window.innerWidth <= 900) {
		return SIDEBAR_WIDTH_MIN;
	}

	return clampSidebarWidth(
		Math.floor(getSidebarAvailableWidth() * SIDEBAR_DEFAULT_RATIO),
	);
}

export function cycleOptionValue<T extends string>(
	current: T,
	options: readonly { value: T }[],
) {
	const currentIndex = options.findIndex((option) => option.value === current);
	const nextIndex =
		currentIndex === -1 ? 0 : (currentIndex + 1) % options.length;
	return options[nextIndex].value;
}
