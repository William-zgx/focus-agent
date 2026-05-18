import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { FocusAgentBrand } from "@/shared/ui/focus-agent-brand";

import { LOGIN_DESTINATIONS } from "./auth-page-data";

function DestinationCard({
	description,
	isActive,
	icon,
	label,
	to,
}: {
	description: string;
	isActive: boolean;
	icon: ReactNode;
	label: string;
	to: string;
}) {
	return (
		<Link
			aria-current={isActive ? "true" : undefined}
			className={`fa-auth-entry-card ${isActive ? "is-selected" : ""}`}
			search={{ return_to: to }}
			to="/auth/login"
		>
			<i aria-hidden="true" className="fa-auth-entry-card-accent" />
			<div className="fa-auth-entry-card-leading">
				<span className="fa-auth-entry-card-icon-shell">{icon}</span>
				<i aria-hidden="true" className="fa-auth-entry-card-check" />
			</div>
			<strong className="fa-auth-entry-card-label">{label}</strong>
			<span className="fa-auth-entry-card-description">{description}</span>
		</Link>
	);
}

export function LoginIntro({
	effectiveReturnTo,
}: {
	effectiveReturnTo: string;
}) {
	return (
		<section className="fa-auth-login-intro">
			<div className="fa-auth-login-brand">
				<FocusAgentBrand />
			</div>
			<h1>进入 Focus Agent</h1>
			<p className="fa-auth-description">
				选择登录后的目标页面，验证身份后直接回到对应工作区。
			</p>
			<ul className="fa-auth-feature-segmented" aria-label="登录后功能分区">
				<li
					aria-current={effectiveReturnTo === "/" ? "true" : undefined}
					className={`fa-auth-feature-segment ${effectiveReturnTo === "/" ? "is-selected" : ""}`}
				>
					对话
				</li>
				<li
					aria-current={
						effectiveReturnTo === "/agent-team" ? "true" : undefined
					}
					className={`fa-auth-feature-segment ${effectiveReturnTo === "/agent-team" ? "is-selected" : ""}`}
				>
					团队协作
				</li>
				<li
					aria-current={
						effectiveReturnTo === "/observability/trajectory"
							? "true"
							: undefined
					}
					className={`fa-auth-feature-segment ${
						effectiveReturnTo === "/observability/trajectory"
							? "is-selected"
							: ""
					}`}
				>
					复盘台
				</li>
			</ul>
			<div className="fa-auth-entry-grid">
				{LOGIN_DESTINATIONS.map((destination) => (
					<DestinationCard
						icon={destination.icon}
						description={destination.description}
						isActive={destination.to === effectiveReturnTo}
						key={destination.to}
						label={destination.label}
						to={destination.to}
					/>
				))}
			</div>
		</section>
	);
}
