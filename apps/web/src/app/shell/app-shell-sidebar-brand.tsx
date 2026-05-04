import type { FocusEventHandler, MouseEventHandler } from "react";

import type { ColorPreference, LanguagePreference, ThemePreference } from "@/app/shell/shell-ui-context";
import { SidebarToggleIcon, renderThemeIcon } from "@/app/shell/app-shell-icons";
import { FocusAgentBrand } from "@/shared/ui/focus-agent-brand";
import { tooltipProps } from "@/shared/ui/tooltip";

type TooltipInteractionHandlers = {
  onBlur: FocusEventHandler<HTMLElement>;
  onFocus: FocusEventHandler<HTMLElement>;
  onMouseEnter: MouseEventHandler<HTMLElement>;
  onMouseLeave: MouseEventHandler<HTMLElement>;
};

type AppShellSidebarBrandProps = {
  colorPreference: ColorPreference;
  cycleColor: () => void;
  cycleLanguage: () => void;
  cycleTheme: () => void;
  isChineseUi: boolean;
  languagePreference: LanguagePreference;
  selectedColorLabel: string;
  selectedLanguage: {
    shortLabel: string;
  };
  selectedLanguageLabel: string;
  selectedThemeLabel: string;
  themePreference: ThemePreference;
  tooltipHandlers: TooltipInteractionHandlers;
  toggleSidebar: () => void;
};

export function AppShellSidebarBrand({
  colorPreference,
  cycleColor,
  cycleLanguage,
  cycleTheme,
  isChineseUi,
  languagePreference,
  selectedColorLabel,
  selectedLanguage,
  selectedLanguageLabel,
  selectedThemeLabel,
  themePreference,
  tooltipHandlers,
  toggleSidebar,
}: AppShellSidebarBrandProps) {
  return (
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
                isChineseUi ? `语言：${selectedLanguageLabel}` : `Language: ${selectedLanguageLabel}`,
              )}
              {...tooltipHandlers}
              onClick={cycleLanguage}
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
              {...tooltipProps(isChineseUi ? `主题：${selectedThemeLabel}` : `Theme: ${selectedThemeLabel}`)}
              {...tooltipHandlers}
              onClick={cycleTheme}
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
              {...tooltipProps(isChineseUi ? `色系：${selectedColorLabel}` : `Color: ${selectedColorLabel}`)}
              {...tooltipHandlers}
              onClick={cycleColor}
              type="button"
            >
              <span className="fa-sidebar-color-swatch-dot" aria-hidden="true" />
            </button>
          </div>
          <button
            className="fa-sidebar-toggle-button"
            {...tooltipProps(isChineseUi ? "收起侧栏" : "Collapse sidebar")}
            {...tooltipHandlers}
            onClick={toggleSidebar}
            type="button"
            aria-label={isChineseUi ? "收起侧栏" : "Collapse sidebar"}
          >
            <SidebarToggleIcon collapsed={false} />
          </button>
        </div>
      </div>
    </div>
  );
}
