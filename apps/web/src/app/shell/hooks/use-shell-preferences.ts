import { type CSSProperties, useEffect, useState } from "react";

import {
	COLOR_OPTIONS,
	COLOR_KEY,
	DEFAULT_COLOR_PREFERENCE,
	DEFAULT_LANGUAGE_PREFERENCE,
	DEFAULT_THEME_PREFERENCE,
	LANGUAGE_KEY,
	LANGUAGE_OPTIONS,
	THEME_KEY,
	THEME_OPTIONS,
	SIDEBAR_COLLAPSED_KEY,
	SIDEBAR_WIDTH_KEY,
	clampSidebarWidth,
	getSidebarDefaultWidth,
	getSidebarViewportMax,
	cycleOptionValue,
} from "@/app/shell/app-shell-config";
import type {
	ColorPreference,
	LanguagePreference,
	ThemePreference,
} from "@/app/shell/shell-ui-context";

export function useShellPreferences() {
	const [languagePreference, setLanguagePreference] =
		useState<LanguagePreference>(DEFAULT_LANGUAGE_PREFERENCE);
	const [themePreference, setThemePreference] = useState<ThemePreference>(
		DEFAULT_THEME_PREFERENCE,
	);
	const [colorPreference, setColorPreference] = useState<ColorPreference>(
		DEFAULT_COLOR_PREFERENCE,
	);
	const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
	const [sidebarWidth, setSidebarWidth] = useState(() =>
		getSidebarDefaultWidth(),
	);
	const isChineseUi = languagePreference === "zh";
	const shellStyle = {
		"--fa-sidebar-width": `${sidebarWidth}px`,
	} as CSSProperties;

	useEffect(() => {
		const urlLanguage = new URLSearchParams(window.location.search).get("lang");
		if (urlLanguage === "en" || urlLanguage === "zh") {
			setLanguagePreference(urlLanguage);
		}
		const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
		if (stored === "1" || (stored === null && window.innerWidth <= 900)) {
			setSidebarCollapsed(true);
		}
		const rawWidth = Number.parseInt(
			window.localStorage.getItem(SIDEBAR_WIDTH_KEY) ?? "",
			10,
		);
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
		if (
			savedTheme === "system" ||
			savedTheme === "light" ||
			savedTheme === "dark"
		) {
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
		window.localStorage.setItem(
			SIDEBAR_COLLAPSED_KEY,
			sidebarCollapsed ? "1" : "0",
		);
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
			themePreference === "system"
				? media.matches
					? "light"
					: "dark"
				: themePreference;
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

	const selectedLanguage =
		LANGUAGE_OPTIONS.find((option) => option.value === languagePreference) ??
		LANGUAGE_OPTIONS[0];
	const selectedTheme =
		THEME_OPTIONS.find((option) => option.value === themePreference) ??
		THEME_OPTIONS[0];
	const selectedColor =
		COLOR_OPTIONS.find((option) => option.value === colorPreference) ??
		COLOR_OPTIONS[0];

	return {
		languagePreference,
		setLanguagePreference,
		themePreference,
		setThemePreference,
		colorPreference,
		setColorPreference,
		sidebarCollapsed,
		setSidebarCollapsed,
		sidebarWidth,
		setSidebarWidth,
		isChineseUi,
		shellStyle,
		selectedLanguage,
		selectedTheme,
		selectedColor,
		getSidebarViewportMax,
		cycleLanguage: () => {
			setLanguagePreference((value) =>
				cycleOptionValue(value, LANGUAGE_OPTIONS),
			);
		},
		cycleTheme: () => {
			setThemePreference((value) => cycleOptionValue(value, THEME_OPTIONS));
		},
		cycleColor: () => {
			setColorPreference((value) => cycleOptionValue(value, COLOR_OPTIONS));
		},
	};
}
