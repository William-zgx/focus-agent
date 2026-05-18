import { Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function AccountSecurityPage() {
	const { client, logout } = useFocusAgent();
	const [currentPassword, setCurrentPassword] = useState("");
	const [newPassword, setNewPassword] = useState("");
	const [confirmPassword, setConfirmPassword] = useState("");
	const [message, setMessage] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState<"password" | "logout" | null>(
		null,
	);
	const canSubmit =
		currentPassword &&
		newPassword &&
		newPassword === confirmPassword &&
		submitting === null;

	async function handleChangePassword(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setMessage(null);
		setError(null);
		if (newPassword !== confirmPassword) {
			setError("两次输入的密码不一致。");
			return;
		}
		setSubmitting("password");
		try {
			await client.changePassword({
				current_password: currentPassword,
				new_password: newPassword,
			});
			setCurrentPassword("");
			setNewPassword("");
			setConfirmPassword("");
			setMessage("密码已更新。");
		} catch (nextError: unknown) {
			setError(
				nextError instanceof Error ? nextError.message : "修改密码失败。",
			);
		} finally {
			setSubmitting(null);
		}
	}

	async function handleLogout() {
		setSubmitting("logout");
		try {
			await logout();
		} finally {
			setSubmitting(null);
		}
	}

	return (
		<div className="fa-account-layout">
			<section className="fa-account-panel">
				<div className="fa-account-header">
					<p>账户</p>
					<h1>安全设置</h1>
				</div>
				<nav aria-label="账户页面导航" className="fa-account-nav">
					<Link className="fa-route-state-link" to="/auth">
						返回入口
					</Link>
					<Link className="fa-route-state-link" to="/account/profile">
						个人资料
					</Link>
					<Link className="fa-route-state-link" to="/account/sessions">
						会话管理
					</Link>
				</nav>

				{error ? (
					<div className="fa-inline-notice is-danger">{error}</div>
				) : null}
				{message ? (
					<div className="fa-inline-notice is-success">{message}</div>
				) : null}

				<form className="fa-auth-form" onSubmit={handleChangePassword}>
					<label>
						当前密码
						<input
							autoComplete="current-password"
							onChange={(event) => setCurrentPassword(event.target.value)}
							type="password"
							value={currentPassword}
						/>
					</label>
					<label>
						新密码
						<input
							autoComplete="new-password"
							onChange={(event) => setNewPassword(event.target.value)}
							type="password"
							value={newPassword}
						/>
					</label>
					<label>
						确认新密码
						<input
							autoComplete="new-password"
							onChange={(event) => setConfirmPassword(event.target.value)}
							type="password"
							value={confirmPassword}
						/>
					</label>
					<div className="fa-auth-actions">
						<button
							className="fa-auth-button is-primary"
							disabled={!canSubmit}
							type="submit"
						>
							{submitting === "password" ? "保存中..." : "更新密码"}
						</button>
						<button
							className="fa-auth-button"
							disabled={Boolean(submitting)}
							onClick={handleLogout}
							type="button"
						>
							{submitting === "logout" ? "退出中..." : "退出"}
						</button>
					</div>
				</form>
			</section>
		</div>
	);
}
