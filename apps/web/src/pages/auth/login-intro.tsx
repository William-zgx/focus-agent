import { Link } from "@tanstack/react-router";
import { type ReactNode } from "react";

import { LOGIN_DESTINATIONS } from "./auth-page-data";

function DestinationCard({
  description,
  isActive,
  icon,
  label,
  to,
}: {
  description: string;
  isActive: boolean;
  icon: ReactNode;
  label: string;
  to: string;
}) {
  return (
    <Link className={`fa-auth-entry-card ${isActive ? "is-selected" : ""}`} search={{ return_to: to }} to="/auth/login">
      <span className="fa-auth-entry-card-icon-shell">{icon}</span>
      <strong>{label}</strong>
      <span>{description}</span>
    </Link>
  );
}

export function LoginIntro({ effectiveReturnTo }: { effectiveReturnTo: string }) {
  return (
    <section className="fa-auth-login-intro">
      <p className="fa-auth-login-chip">Focus Agent</p>
      <h1>进入 Focus Agent</h1>
      <p className="fa-auth-description">
        选择登录后的目标页面，验证身份后直接回到对应工作区。
      </p>
      <div className="fa-auth-feature-tags">
        <span>对话</span>
        <span>团队协作</span>
        <span>复盘台</span>
      </div>
      <div className="fa-auth-entry-grid">
        {LOGIN_DESTINATIONS.map((destination) => (
          <DestinationCard
            icon={destination.icon}
            description={destination.description}
            isActive={destination.to === effectiveReturnTo}
            key={destination.to}
            label={destination.label}
            to={destination.to}
          />
        ))}
      </div>
    </section>
  );
}
