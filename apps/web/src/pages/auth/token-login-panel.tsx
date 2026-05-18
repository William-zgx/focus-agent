import type { FormEvent } from "react";

import type { LoginSubmitMode } from "./login-page-types";

export function TokenLoginPanel({
	authReady,
	clearStoredToken,
	onTokenSubmit,
	setShowToken,
	setToken,
	showToken,
	submitting,
	token,
}: {
	authReady: boolean;
	clearStoredToken: () => void;
	onTokenSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
	setShowToken: (value: (current: boolean) => boolean) => void;
	setToken: (value: string) => void;
	showToken: boolean;
	submitting: LoginSubmitMode | null;
	token: string;
}) {
	const isSubmitDisabled = !authReady || Boolean(submitting);
	const tokenPanelId = "fa-auth-token-login-panel";

	return (
		<div className="fa-auth-advanced">
			<button
				className="fa-auth-debug-toggle"
				aria-controls={tokenPanelId}
				aria-label="开发者调试"
				aria-expanded={showToken}
				title="开发者调试"
				onClick={() => setShowToken((value) => !value)}
				type="button"
			>
				<svg
					aria-hidden="true"
					className="fa-auth-debug-icon"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					strokeWidth="1.8"
					strokeLinecap="round"
					strokeLinejoin="round"
				>
					<path d="M9 16h6" />
					<path d="M9 8h6" />
					<path d="M8 9l-3 3 3 3" />
					<path d="M16 15l3-3-3-3" />
					<path d="M10.5 6c0-.8.7-1.5 1.5-1.5h0c.8 0 1.5.7 1.5 1.5M10.5 18c0 .8.7 1.5 1.5 1.5h0c.8 0 1.5-.7 1.5-1.5" />
				</svg>
				<span className="sr-only">开发者调试</span>
			</button>
			{showToken ? (
				<form
					className="fa-auth-form fa-auth-debug-form"
					id={tokenPanelId}
					onSubmit={onTokenSubmit}
				>
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
						<button
							className="fa-auth-button"
							disabled={isSubmitDisabled || !token.trim()}
							type="submit"
						>
							{!authReady
								? "准备中..."
								: submitting === "token"
									? "验证中..."
									: "继续"}
						</button>
						<button
							className="fa-auth-button"
							disabled={isSubmitDisabled}
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
	);
}
