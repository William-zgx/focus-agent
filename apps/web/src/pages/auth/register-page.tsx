import { useSearch } from "@tanstack/react-router";
import { type FormEvent, useMemo, useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import { appReturnToPath, normalizeAuthReturnTo } from "./return-to";

export function RegisterPage() {
  const search = useSearch({ strict: false });
  const { authError, registerWithPassword } = useFocusAgent();
  const returnTo = useMemo(() => normalizeAuthReturnTo((search as { return_to?: unknown }).return_to), [search]);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const canSubmit = username.trim() && password && password === confirmPassword && !submitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    if (password !== confirmPassword) {
      setLocalError("两次密码输入不一致。");
      return;
    }
    setSubmitting(true);
    try {
      const ok = await registerWithPassword({
        username: username.trim(),
        password,
        display_name: displayName.trim() || null,
      });
      if (ok) {
        window.location.assign(appReturnToPath(returnTo));
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleBackToLogin() {
    const query = new URLSearchParams({ return_to: returnTo || "/" }).toString();
    window.location.assign(`/app/auth/login?${query}`);
  }

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
        <div className="fa-auth-header">
          <p>Focus Agent</p>
          <h1>创建账号</h1>
        </div>

        {localError || authError ? (
          <div className="fa-inline-notice is-danger">{localError ?? authError}</div>
        ) : null}

        <form className="fa-auth-form" onSubmit={handleSubmit}>
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
            昵称（可选）
            <input
              autoComplete="name"
              onChange={(event) => setDisplayName(event.target.value)}
              type="text"
              value={displayName}
            />
          </label>
          <label>
            密码
            <input
              autoComplete="new-password"
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              value={password}
            />
          </label>
          <label>
            再次确认密码
            <input
              autoComplete="new-password"
              onChange={(event) => setConfirmPassword(event.target.value)}
              type="password"
              value={confirmPassword}
            />
          </label>
          <button className="fa-auth-button is-primary" disabled={!canSubmit} type="submit">
            {submitting ? "创建中..." : "创建账号"}
          </button>
        </form>

        <div className="fa-auth-row">
          <button className="fa-auth-button" onClick={handleBackToLogin} type="button">
            返回登录
          </button>
        </div>
      </section>
    </div>
  );
}
