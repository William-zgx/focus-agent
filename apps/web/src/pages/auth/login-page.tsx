import { Link, useSearch } from "@tanstack/react-router";
import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import {
  AgentTeamIcon,
  BranchFocusIcon,
  TokenUsageIcon,
} from "@/shared/ui/toolbar-icons";

import { appReturnToPath, normalizeAuthReturnTo } from "./return-to";

const LOGIN_DESTINATIONS = [
  {
    description: "发起对话，快速进入会话工作区。",
    label: "正式对话",
    to: "/",
    icon: <BranchFocusIcon className="fa-auth-entry-card-icon" />,
  },
  {
    description: "多人协作，分工推进复杂工作。",
    label: "团队合作",
    to: "/agent-team",
    icon: <AgentTeamIcon className="fa-auth-entry-card-icon" />,
  },
  {
    description: "查看会话轨迹，追踪决策与复盘。",
    label: "复盘台",
    to: "/observability/trajectory",
    icon: <TokenUsageIcon className="fa-auth-entry-card-icon" />,
  },
] as const;

const LOGIN_MOTION_ORBS = [
  {
    className: "fa-auth-orb-one fa-auth-orb-soft",
  },
  {
    className: "fa-auth-orb-two fa-auth-orb-soft",
  },
  {
    className: "fa-auth-orb-four fa-auth-orb-soft",
  },
] as const;

const ACCOUNT_ACTIONS = [
  { description: "管理头像、显示名等资料", label: "账号信息", to: "/account/profile" },
  { description: "修改登录密码", label: "安全设置", to: "/account/security" },
  { description: "查看并关闭其他会话", label: "会话管理", to: "/account/sessions" },
] as const;

const QUICK_START_ACTIONS = [
  { description: "进入主会话和分支任务页", label: "正式对话", to: "/" },
  { description: "进入团队协作工作台", label: "团队合作", to: "/agent-team" },
  { description: "查看轨迹与复盘", label: "复盘台", to: "/observability/trajectory" },
] as const;

const ADMIN_SHORTCUTS = [
  { description: "用户、角色与状态治理", label: "用户管理", to: "/admin/users" },
  { description: "查看审计记录与变更", label: "审计中心", to: "/admin/audit-events" },
] as const;

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

function AccountSummary({ principal, isAdmin }: { isAdmin: boolean; principal: { display_name: string | null; username: string } }) {
  return (
    <div className="fa-auth-hub-user">
      <span>当前账号</span>
      <strong>{principal.display_name || principal.username}</strong>
      <small>{isAdmin ? "管理员" : "普通用户"}</small>
    </div>
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

function AccountPortal({
  returnTo,
  isAdmin,
  logout,
  principal,
}: {
  isAdmin: boolean;
  logout: () => Promise<void>;
  principal: { display_name: string | null; username: string };
  returnTo: string;
}) {
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function handleLogout() {
    if (isLoggingOut) return;
    setIsLoggingOut(true);
    try {
      await logout();
      window.location.assign("/app/auth");
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

export function LoginPage() {
  const search = useSearch({ strict: false });
  const {
    authError,
    authHint,
    isAdmin,
    authenticateWithDemoUser,
    authenticateWithPassword,
    authenticateWithToken,
    logout,
    clearStoredToken,
    principal,
  } = useFocusAgent();
  const returnTo = useMemo(() => normalizeAuthReturnTo((search as { return_to?: unknown }).return_to), [search]);
  const [effectiveReturnTo, setEffectiveReturnTo] = useState(returnTo);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [submitting, setSubmitting] = useState<"password" | "demo" | "token" | null>(null);
  const showsDisabledDemoTokenHint = authHint === "demo_token_disabled";

  useEffect(() => {
    setEffectiveReturnTo(returnTo);
  }, [returnTo]);

  async function finish(ok: boolean) {
    if (ok) {
      window.location.assign(appReturnToPath(effectiveReturnTo));
    }
  }

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password || submitting) return;
    setSubmitting("password");
    try {
      await finish(await authenticateWithPassword({ username: username.trim(), password }));
    } finally {
      setSubmitting(null);
    }
  }

  async function handleTokenSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim() || submitting) return;
    setSubmitting("token");
    try {
      await finish(await authenticateWithToken(token));
    } finally {
      setSubmitting(null);
    }
  }

  async function handleDemoLogin() {
    if (submitting) return;
    setSubmitting("demo");
    try {
      await finish(await authenticateWithDemoUser());
    } finally {
      setSubmitting(null);
    }
  }

  if (principal) {
    const summary = {
      display_name: principal.user?.display_name ?? null,
      username: principal.user?.username ?? principal.user_id,
    };

    return (
      <div className="fa-auth-page">
        <section className="fa-auth-panel fa-auth-login-panel">
          <div className="fa-auth-motion-canvas" aria-hidden="true">
            <span className="fa-auth-motion-mesh" />
            <span className="fa-auth-motion-vignette" />
            <span className="fa-auth-motion-grid-line" />
            <span className="fa-auth-motion-bubble fa-auth-motion-bubble-one" />
            <span className="fa-auth-motion-bubble fa-auth-motion-bubble-two" />
            <span className="fa-auth-motion-ripple" />
          </div>
          <div className="fa-auth-floating-orbs" aria-hidden="true">
            {LOGIN_MOTION_ORBS.map((orb) => (
              <span className={`fa-auth-orb ${orb.className}`} key={orb.className} />
            ))}
          </div>
          <div className="fa-auth-login-shell">
            <AccountPortal isAdmin={isAdmin} logout={logout} principal={summary} returnTo={effectiveReturnTo} />
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="fa-auth-page">
      <section className="fa-auth-panel fa-auth-login-panel">
        <div className="fa-auth-motion-canvas" aria-hidden="true">
          <span className="fa-auth-motion-vignette" />
          <span className="fa-auth-motion-scanline" />
          <span className="fa-auth-motion-grid-line" />
          <span className="fa-auth-motion-ripple" />
          <span className="fa-auth-motion-bubble fa-auth-motion-bubble-one" />
          <span className="fa-auth-motion-bubble fa-auth-motion-bubble-two" />
          <span className="fa-auth-motion-mesh" />
        </div>
        <div className="fa-auth-floating-orbs" aria-hidden="true">
          {LOGIN_MOTION_ORBS.map((orb) => (
            <span className={`fa-auth-orb ${orb.className}`} key={orb.className} />
          ))}
        </div>
        <div className="fa-auth-login-shell">
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

          <section className="fa-auth-login-form">
            <div className="fa-auth-header">
              <p>登录</p>
              <h1>账号登录</h1>
            </div>
            <p className="fa-auth-description">使用用户名与密码完成身份确认，随后进入对应页面。</p>

            {authError ? <div className="fa-inline-notice is-danger">{authError}</div> : null}

            <form className="fa-auth-form" onSubmit={handlePasswordSubmit}>
              <label>
                用户名
                <input
                  autoComplete="username"
                  autoFocus
                  onChange={(event) => setUsername(event.target.value)}
                  type="text"
                  value={username}
                />
              </label>
              <label>
                密码
                <input
                  autoComplete="current-password"
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  value={password}
                />
              </label>
              <button
                className="fa-auth-button is-primary"
                disabled={Boolean(submitting) || !username.trim() || !password}
                type="submit"
              >
                {submitting === "password" ? "登录中..." : "登录"}
              </button>
            </form>

            <div className="fa-auth-row">
              <Link search={{ return_to: effectiveReturnTo }} to="/auth/register">
                没有账号？先去注册
              </Link>
              {!showsDisabledDemoTokenHint ? (
                <button disabled={Boolean(submitting)} onClick={handleDemoLogin} type="button">
                  {submitting === "demo" ? "示例登录中..." : "Demo 登录"}
                </button>
              ) : null}
            </div>
          </section>
        </div>

        <div className="fa-auth-advanced">
          <button onClick={() => setShowToken((value) => !value)} type="button">
            使用 Bearer Token
          </button>
          {showToken ? (
            <form className="fa-auth-form" onSubmit={handleTokenSubmit}>
              <label>
                Access token
                <textarea
                  onChange={(event) => setToken(event.target.value)}
                  rows={4}
                  spellCheck={false}
                  value={token}
                />
              </label>
              <div className="fa-auth-actions">
                <button className="fa-auth-button" disabled={Boolean(submitting) || !token.trim()} type="submit">
                  {submitting === "token" ? "验证中..." : "继续"}
                </button>
                <button
                  className="fa-auth-button"
                  disabled={Boolean(submitting)}
                  onClick={() => {
                    setToken("");
                    clearStoredToken();
                  }}
                  type="button"
                >
                  清空
                </button>
              </div>
            </form>
          ) : null}
        </div>
      </section>
    </div>
  );
}
