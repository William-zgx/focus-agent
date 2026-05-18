import { Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";

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
	const [isPasswordVisible, setIsPasswordVisible] = useState(false);
	const isSubmitDisabled = !authReady || Boolean(submitting);
	const usernameInputId = "fa-auth-login-username";
	const passwordInputId = "fa-auth-login-password";
	const passwordToggleLabel = isPasswordVisible ? "隐藏密码" : "显示密码";

	return (
		<section className="fa-auth-login-form">
			<div className="fa-auth-login-form-heading">
				<div className="fa-auth-header">
					<h1>登录并继续工作</h1>
				</div>
			</div>

			{authError ? (
				<div className="fa-inline-notice is-danger" role="alert">
					{authError}
				</div>
			) : null}

			<form className="fa-auth-form" onSubmit={onPasswordSubmit}>
				<div className="fa-auth-field">
					<label htmlFor={usernameInputId}>用户名</label>
					<input
						autoComplete="username"
						id={usernameInputId}
						onChange={(event) => setUsername(event.target.value)}
						placeholder="name@example.com 或用户名"
						type="text"
						value={username}
					/>
				</div>
				<div className="fa-auth-field fa-auth-password-field">
					<label htmlFor={passwordInputId}>密码</label>
					<span className="fa-auth-password-control fa-auth-password-control-inline">
						<input
							autoComplete="current-password"
							className="fa-auth-password-input"
							id={passwordInputId}
							onChange={(event) => setPassword(event.target.value)}
							placeholder="输入登录密码"
							type={isPasswordVisible ? "text" : "password"}
							value={password}
						/>
						<button
							aria-controls={passwordInputId}
							aria-label={passwordToggleLabel}
							aria-pressed={isPasswordVisible}
							className="fa-auth-password-action fa-auth-password-inline-action"
							onClick={() => setIsPasswordVisible((value) => !value)}
							type="button"
						>
							{isPasswordVisible ? "隐藏" : "显示"}
						</button>
					</span>
				</div>
				<button
					className="fa-auth-button is-primary"
					disabled={isSubmitDisabled || !username.trim() || !password}
					type="submit"
				>
					{!authReady
						? "准备中..."
						: submitting === "password"
							? "登录中..."
							: "登录并继续"}
				</button>
			</form>

			<div className="fa-auth-row">
				<Link
					className="fa-auth-secondary-link fa-auth-secondary-register"
					search={{ return_to: effectiveReturnTo }}
					to="/auth/register"
				>
					创建账号
				</Link>
				{!showsDisabledDemoTokenHint ? (
					<button
						className="fa-auth-secondary-link fa-auth-secondary-demo"
						disabled={isSubmitDisabled}
						onClick={() => void onDemoLogin()}
						type="button"
					>
						{submitting === "demo" ? "正在进入 Demo..." : "试用 Demo 工作区"}
					</button>
				) : null}
			</div>
		</section>
	);
}
