import type { ReactNode } from "react";

interface FocusAgentBrandProps {
  compact?: boolean;
  title?: string;
  subtitle?: string;
  titleAddon?: ReactNode;
}

export function FocusAgentBrand({
  compact = false,
  title = "Focus Agent",
  subtitle,
  titleAddon,
}: FocusAgentBrandProps) {
  return (
    <div className={`fa-brand-lockup ${compact ? "is-compact" : ""}`}>
      <span className="fa-brand-mark" aria-hidden="true">
        <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient
              id="focus-agent-brand-accent"
              x1="10"
              y1="8"
              x2="38"
              y2="40"
              gradientUnits="userSpaceOnUse"
            >
              <stop offset="0" stopColor="#0F62FE" />
              <stop offset="1" stopColor="#6BA9FF" />
            </linearGradient>
          </defs>
          <circle
            cx="16.5"
            cy="24"
            r="8.5"
            stroke="url(#focus-agent-brand-accent)"
            strokeWidth="3"
          />
          <circle cx="16.5" cy="24" r="3.25" fill="url(#focus-agent-brand-accent)" />
          <path
            d="M25 24H31V15.5H37.5"
            stroke="#1D3557"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M31 24V32.5H37.5"
            stroke="#1D3557"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="37.5" cy="15.5" r="3.1" fill="#1D3557" />
          <circle cx="31" cy="24" r="3.1" fill="#1D3557" />
          <circle cx="37.5" cy="32.5" r="3.1" fill="#1D3557" />
        </svg>
      </span>
      <span className="fa-brand-copy">
        <span className="fa-brand-title-row">
          <span className="fa-brand-title">{title}</span>
          {titleAddon}
        </span>
        {subtitle ? <span className="fa-brand-subtitle">{subtitle}</span> : null}
      </span>
    </div>
  );
}
