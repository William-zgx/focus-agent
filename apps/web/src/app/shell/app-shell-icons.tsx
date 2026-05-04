import type { ThemePreference } from "@/app/shell/shell-ui-context";

type SidebarToggleIconProps = {
  collapsed: boolean;
};

export function SidebarToggleIcon({ collapsed }: SidebarToggleIconProps) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="4.15" y="4" width="2.2" height="12" rx="1.1" fill="currentColor" opacity="0.96" />
      <path
        d={
          collapsed
            ? "M8.4 6.45v7.1c0 .42.49.64.8.35l3.8-3.55a.48.48 0 0 0 0-.7L9.2 6.1c-.31-.29-.8-.07-.8.35Z"
            : "M12.85 6.1 9.05 9.65a.48.48 0 0 0 0 .7l3.8 3.55c.31.29.8.07.8-.35V6.45c0-.42-.49-.64-.8-.35Z"
        }
        fill="currentColor"
      />
    </svg>
  );
}

export function renderThemeIcon(value: ThemePreference) {
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
