import { Link } from "@tanstack/react-router";
import type { FormEvent } from "react";

import type { LoginSubmitMode } from "./login-page-types";

export function LoginForm({
	authReady,
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
	authReady: boolean;
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
	const isSubmitDisabled = !authReady || Boolean(submitting);

	return (
		<section className="fa-auth-login-form">
			<div className="fa-auth-login-form-heading">
				<div className="fa-auth-header">
					<p>登录</p>
					<h1>账号登录</h1>
				</div>
				<div className="fa-auth-security-badge">
					<span className="fa-auth-security-badge-icon" aria-hidden="true">
						<svg
							fill="none"
							viewBox="0 0 16 16"
							xmlns="http://www.w3.org/2000/svg"
							aria-hidden="true"
						>
							<path
								d="M8 1.25 13 3.2v3.56c0 3.13-1.91 5.99-4.82 7.24L8 14.25l-.18-.07C4.91 12.95 3 10.09 3 6.76V3.2l5-1.95Z"
								stroke="currentColor"
								strokeLinecap="round"
								strokeLinejoin="round"
							/>
							<path
								d="m5.65 8 1.63 1.66 3.07-3.16"
								stroke="currentColor"
								strokeLinecap="round"
								strokeLinejoin="round"
							/>
						</svg>
					</span>
					<span className="fa-auth-security-badge-text">安全验证</span>
				</div>
			</div>
			<p className="fa-auth-description">
				使用用户名与密码完成身份确认，随后进入对应页面。
			</p>

			{authError ? (
				<div className="fa-inline-notice is-danger">{authError}</div>
			) : null}

			<form className="fa-auth-form" onSubmit={onPasswordSubmit}>
				<label>
					用户名
					<input
						autoComplete="username"
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
					disabled={isSubmitDisabled || !username.trim() || !password}
					type="submit"
				>
					{!authReady
						? "准备中..."
						: submitting === "password"
							? "登录中..."
							: "登录"}
				</button>
			</form>

			<div className="fa-auth-row">
				<Link search={{ return_to: effectiveReturnTo }} to="/auth/register">
					没有账号？先去注册
				</Link>
				{!showsDisabledDemoTokenHint ? (
					<button
						disabled={isSubmitDisabled}
						onClick={() => void onDemoLogin()}
						type="button"
					>
						{submitting === "demo" ? "示例登录中..." : "Demo 登录"}
					</button>
				) : null}
			</div>
		</section>
	);
}
