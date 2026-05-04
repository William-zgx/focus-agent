import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { ACCOUNT_ACTIONS, ADMIN_SHORTCUTS, QUICK_START_ACTIONS } from "./auth-page-data";
import { appAuthPath, appReturnToPath } from "./return-to";
import { type LoginPrincipalSummary } from "./login-page-types";

function AccountSummary({
  isAdmin,
  principal,
}: {
  isAdmin: boolean;
  principal: LoginPrincipalSummary;
}) {
  return (
    <div className="fa-auth-hub-user">
      <span>当前账号</span>
      <strong>{principal.display_name || principal.username}</strong>
      <small>{isAdmin ? "管理员" : "普通用户"}</small>
    </div>
  );
}

function HubCard({
  description,
  label,
  search,
  to,
}: {
  description: string;
  label: string;
  search?: Record<string, string>;
  to: string;
}) {
  return (
    <Link className="fa-auth-hub-card" search={search} to={to}>
      <strong>{label}</strong>
      <span>{description}</span>
    </Link>
  );
}

function QuickActions({ returnTo }: { returnTo: string }) {
  return (
    <>
      <section className="fa-auth-hub-section">
        <h2>开始</h2>
        <div className="fa-auth-hub-grid">
          {QUICK_START_ACTIONS.map((card) => (
            <HubCard description={card.description} label={card.label} to={card.to} key={card.to} />
          ))}
        </div>
      </section>
      <section className="fa-auth-hub-section">
        <h2>账号</h2>
        <div className="fa-auth-hub-grid">
          {ACCOUNT_ACTIONS.map((card) => (
            <HubCard description={card.description} label={card.label} to={card.to} key={card.to} />
          ))}
        </div>
      </section>
      {returnTo !== "/" ? (
        <button
          className="fa-auth-button is-primary"
          onClick={() => {
            window.location.assign(appReturnToPath(returnTo));
          }}
          type="button"
        >
          返回上次目标页
        </button>
      ) : null}
    </>
  );
}

export function AccountPortal({
  returnTo,
  isAdmin,
  logout,
  principal,
}: {
  isAdmin: boolean;
  logout: () => Promise<void>;
  principal: LoginPrincipalSummary;
  returnTo: string;
}) {
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function handleLogout() {
    if (isLoggingOut) return;
    setIsLoggingOut(true);
    try {
      await logout();
      window.location.assign(appAuthPath("/login", returnTo));
    } finally {
      setIsLoggingOut(false);
    }
  }

  return (
    <section className="fa-auth-login-intro">
      <p className="fa-auth-login-chip">Focus Agent</p>
      <h1>你的工作入口</h1>
      <p className="fa-auth-description">快速进入对话、协作与复盘场景，也可以管理当前账号。</p>
      <div className="fa-auth-feature-list">
        <strong>登录身份已激活</strong>
        <p>当前账号可直接访问已授权的页面。</p>
      </div>
      <AccountSummary isAdmin={isAdmin} principal={principal} />

      <QuickActions returnTo={returnTo} />

      {isAdmin ? (
        <section className="fa-auth-hub-section">
          <h2>管理员</h2>
          <div className="fa-auth-hub-grid">
            {ADMIN_SHORTCUTS.map((card) => (
              <HubCard description={card.description} label={card.label} to={card.to} key={card.to} />
            ))}
          </div>
        </section>
      ) : null}

      <div className="fa-auth-actions">
        <button className="fa-auth-button" disabled={isLoggingOut} onClick={() => void handleLogout()} type="button">
          {isLoggingOut ? "正在退出..." : "退出登录"}
        </button>
      </div>
    </section>
  );
}
