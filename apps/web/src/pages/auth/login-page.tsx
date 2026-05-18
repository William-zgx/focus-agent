import { useSearch } from "@tanstack/react-router";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import {
	AccountPortal,
	LoginForm,
	LoginIntro,
	LoginPageShell,
	type LoginPrincipalSummary,
	type LoginSubmitMode,
	TokenLoginPanel,
} from "./login-page-sections";
import { appReturnToPath, normalizeAuthReturnTo } from "./return-to";

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
		ready,
	} = useFocusAgent();
	const returnTo = useMemo(
		() => normalizeAuthReturnTo((search as { return_to?: unknown }).return_to),
		[search],
	);
	const [effectiveReturnTo, setEffectiveReturnTo] = useState(returnTo);
	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
	const [token, setToken] = useState("");
	const [showToken, setShowToken] = useState(false);
	const [submitting, setSubmitting] = useState<LoginSubmitMode | null>(null);
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
		if (!ready || !username.trim() || !password || submitting) return;
		setSubmitting("password");
		try {
			await finish(
				await authenticateWithPassword({ username: username.trim(), password }),
			);
		} finally {
			setSubmitting(null);
		}
	}

	async function handleTokenSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (!ready || !token.trim() || submitting) return;
		setSubmitting("token");
		try {
			await finish(await authenticateWithToken(token));
		} finally {
			setSubmitting(null);
		}
	}

	async function handleDemoLogin() {
		if (!ready || submitting) return;
		setSubmitting("demo");
		try {
			await finish(await authenticateWithDemoUser());
		} finally {
			setSubmitting(null);
		}
	}

	if (ready && principal) {
		const summary: LoginPrincipalSummary = {
			display_name: principal.user?.display_name ?? null,
			username: principal.user?.username ?? principal.user_id,
		};

		return (
			<LoginPageShell motionVariant="account">
				<AccountPortal
					isAdmin={isAdmin}
					logout={logout}
					principal={summary}
					returnTo={effectiveReturnTo}
				/>
			</LoginPageShell>
		);
	}

	return (
		<LoginPageShell motionVariant="login">
			<div className="fa-auth-login-access">
				<LoginForm
					authReady={ready}
					authError={authError ?? null}
					effectiveReturnTo={effectiveReturnTo}
					onDemoLogin={handleDemoLogin}
					onPasswordSubmit={handlePasswordSubmit}
					password={password}
					setPassword={setPassword}
					setUsername={setUsername}
					showsDisabledDemoTokenHint={showsDisabledDemoTokenHint}
					submitting={submitting}
					username={username}
				/>
				<TokenLoginPanel
					authReady={ready}
					clearStoredToken={clearStoredToken}
					onTokenSubmit={handleTokenSubmit}
					setShowToken={setShowToken}
					setToken={setToken}
					showToken={showToken}
					submitting={submitting}
					token={token}
				/>
			</div>
			<LoginIntro />
		</LoginPageShell>
	);
}
