import { type FormEvent, useState } from "react";

import { normalizeApiBaseUrl } from "@/shared/config/env";

export function ApiBaseUrlPanel({
	apiBaseUrl,
	apiBaseUrlRequired,
	onSave,
}: {
	apiBaseUrl: string;
	apiBaseUrlRequired: boolean;
	onSave: (value: string) => boolean;
}) {
	const [draft, setDraft] = useState(apiBaseUrl);
	const [error, setError] = useState<string | null>(null);
	const inputId = "fa-auth-api-base-url";
	const normalizedDraft = normalizeApiBaseUrl(draft);
	const isMissingRequiredUrl = apiBaseUrlRequired && !apiBaseUrl;

	function handleSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (!normalizedDraft) {
			setError("请输入有效的 http:// 或 https:// Focus Agent 服务地址。");
			return;
		}
		if (!onSave(normalizedDraft)) {
			setError("服务地址格式无效。");
			return;
		}
		setDraft(normalizedDraft);
		setError(null);
	}

	return (
		<section className="fa-auth-login-form">
			<div className="fa-auth-login-form-heading">
				<div className="fa-auth-header">
					<p>Android</p>
					<h1>连接 Focus Agent 服务</h1>
				</div>
			</div>
			<p className="fa-auth-description">
				{isMissingRequiredUrl
					? "Android 端需要先指定后端地址。"
					: "当前 Android 端会连接到这个后端。"}
			</p>
			<form className="fa-auth-form" onSubmit={handleSubmit}>
				<div className="fa-auth-field">
					<label htmlFor={inputId}>服务地址</label>
					<input
						autoCapitalize="none"
						autoComplete="url"
						id={inputId}
						inputMode="url"
						onChange={(event) => setDraft(event.target.value)}
						placeholder="https://focus-agent.example.com"
						spellCheck={false}
						type="url"
						value={draft}
					/>
				</div>
				<div className="fa-auth-actions">
					<button
						className="fa-auth-button"
						disabled={!normalizedDraft}
						type="submit"
					>
						保存
					</button>
				</div>
			</form>
			{apiBaseUrl ? (
				<p className="fa-auth-description">当前：{apiBaseUrl}</p>
			) : null}
			{error ? (
				<div className="fa-inline-notice is-danger" role="alert">
					{error}
				</div>
			) : null}
		</section>
	);
}
