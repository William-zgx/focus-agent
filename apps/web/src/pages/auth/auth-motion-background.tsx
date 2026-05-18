import type { ReactNode } from "react";

function AuthMotionCanvas({ variant }: { variant: "account" | "login" }) {
	return (
		<div className="fa-auth-motion-canvas" aria-hidden="true">
			{variant === "account" ? (
				<>
					<span className="fa-auth-motion-mesh" />
					<span className="fa-auth-motion-vignette" />
				</>
			) : (
				<>
					<span className="fa-auth-motion-vignette" />
					<span className="fa-auth-motion-mesh" />
				</>
			)}
		</div>
	);
}

export function LoginPageShell({
	children,
	motionVariant,
}: {
	children: ReactNode;
	motionVariant: "account" | "login";
}) {
	const panelVariantClass =
		motionVariant === "account" ? "is-account-panel" : "is-login-panel";

	return (
		<main className="fa-auth-page">
			<section
				className={`fa-auth-panel fa-auth-login-panel ${panelVariantClass}`}
			>
				<AuthMotionCanvas variant={motionVariant} />
				<div
					className={`fa-auth-login-shell ${motionVariant === "account" ? "is-account" : ""}`}
				>
					{children}
				</div>
			</section>
		</main>
	);
}
