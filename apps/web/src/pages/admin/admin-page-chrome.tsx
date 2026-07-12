import { Link } from "@tanstack/react-router";
import type { PropsWithChildren, ReactNode } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { appEnv } from "@/shared/config/env";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

type AdminRouteKey = "users" | "audit" | "config";

type AdminConsoleLayoutProps = {
	active: AdminRouteKey;
	children: ReactNode;
	drawer?: ReactNode;
	drawerLabel?: string;
	side?: ReactNode;
	summary: string;
	title: string;
	toolbar?: ReactNode;
	allowDeviceLocalConfiguration?: boolean;
};

export function AdminAccessGate({
	allowDeviceLocalConfiguration = false,
	children,
}: PropsWithChildren<{ allowDeviceLocalConfiguration?: boolean }>) {
	const { isAdmin, logout } = useFocusAgent();
	const { isChineseUi } = useShellUi();

	if (!isAdmin && !(allowDeviceLocalConfiguration && appEnv.useLocalRuntime)) {
		return (
			<div className="fa-admin-layout">
				<section className="fa-admin-panel fa-admin-denied">
					<p className="fa-admin-eyebrow">{isChineseUi ? "Admin" : "Admin"}</p>
					<h1>{isChineseUi ? "需要管理员权限" : "Admin Access Required"}</h1>
					<p>
						{isChineseUi
							? "当前会话没有管理员角色或管理员标记。"
							: "The current principal does not include an admin role or admin flag."}
					</p>
					<div className="fa-auth-actions">
						<Link className="fa-route-state-link" to="/auth">
							{isChineseUi ? "返回 /auth" : "Return to /auth"}
						</Link>
						<button
							className="fa-auth-button"
							onClick={() => void logout()}
							type="button"
						>
							{isChineseUi
								? "切换账号 / 退出登录"
								: "Switch account / sign out"}
						</button>
					</div>
				</section>
			</div>
		);
	}

	return <>{children}</>;
}

export function AdminConsoleLayout({
	children,
	drawer,
	drawerLabel,
	side,
	summary,
	title,
	toolbar,
	allowDeviceLocalConfiguration = false,
}: AdminConsoleLayoutProps) {
	return (
		<AdminAccessGate
			allowDeviceLocalConfiguration={allowDeviceLocalConfiguration}
		>
			<div className="fa-admin-layout">
				<div className={`fa-admin-console ${drawer ? "has-drawer" : ""}`}>
					<section className="fa-admin-console-main">
						<AdminPageHeading
							deviceLocalConfiguration={allowDeviceLocalConfiguration}
							title={title}
							summary={summary}
							side={side}
							toolbar={toolbar}
						/>
						{children}
					</section>
					{drawer ? (
						<aside className="fa-admin-console-drawer" aria-label={drawerLabel}>
							{drawer}
						</aside>
					) : null}
				</div>
			</div>
		</AdminAccessGate>
	);
}

export function AdminPageHeading({
	deviceLocalConfiguration = false,
	title,
	summary,
	side,
	toolbar,
}: {
	deviceLocalConfiguration?: boolean;
	title: string;
	summary: string;
	side?: ReactNode;
	toolbar?: ReactNode;
}) {
	const { isChineseUi } = useShellUi();

	return (
		<section className="fa-admin-page-bar">
			<div className="fa-trajectory-workbench-header-copy">
				<div className="fa-trajectory-workbench-heading fa-admin-workspace-heading">
					<p className="fa-admin-eyebrow">
						{deviceLocalConfiguration && appEnv.useLocalRuntime
							? isChineseUi
								? "设备本地配置"
								: "Device-local configuration"
							: isChineseUi
								? "系统管理 / 治理"
								: "System Administration / Governance"}
					</p>
					<h1>{title}</h1>
					<p>{summary}</p>
				</div>
				{side || toolbar ? (
					<div className="fa-trajectory-workbench-header-side">
						{side}
						{toolbar ? (
							<div className="fa-admin-console-toolbar">{toolbar}</div>
						) : null}
					</div>
				) : null}
			</div>
		</section>
	);
}

export function AdminErrorMessage({
	error,
	fallback,
}: {
	error: unknown;
	fallback: string;
}) {
	return (
		<div className="fa-inline-notice is-danger">
			{error instanceof Error ? error.message : fallback}
		</div>
	);
}
