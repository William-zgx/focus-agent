import { Link } from "@tanstack/react-router";
import { type FormEvent } from "react";

import { type LoginSubmitMode } from "./login-page-types";

export function LoginForm({
  authError,
  effectiveReturnTo,
  onDemoLogin,
  onPasswordSubmit,
  password,
  setPassword,
  setUsername,
  showsDisabledDemoTokenHint,
  submitting,
  username,
}: {
  authError: string | null;
  effectiveReturnTo: string;
  onDemoLogin: () => Promise<void>;
  onPasswordSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  password: string;
  setPassword: (value: string) => void;
  setUsername: (value: string) => void;
  showsDisabledDemoTokenHint: boolean;
  submitting: LoginSubmitMode | null;
  username: string;
}) {
  return (
    <section className="fa-auth-login-form">
      <div className="fa-auth-header">
        <p>登录</p>
        <h1>账号登录</h1>
      </div>
      <p className="fa-auth-description">使用用户名与密码完成身份确认，随后进入对应页面。</p>

      {authError ? <div className="fa-inline-notice is-danger">{authError}</div> : null}

      <form className="fa-auth-form" onSubmit={onPasswordSubmit}>
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
          <button disabled={Boolean(submitting)} onClick={() => void onDemoLogin()} type="button">
            {submitting === "demo" ? "示例登录中..." : "Demo 登录"}
          </button>
        ) : null}
      </div>
    </section>
  );
}
