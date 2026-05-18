import loginVisualUrl from "@/assets/auth/focus-agent-login-visual.png";
import { FocusAgentBrand } from "@/shared/ui/focus-agent-brand";

export function LoginIntro() {
	return (
		<section className="fa-auth-login-intro">
			<div className="fa-auth-login-brand">
				<FocusAgentBrand />
			</div>
			<h1>分支优先的 Agent 工作台</h1>
			<p className="fa-auth-description">
				让长任务在对话、任务分工和证据复盘之间保持清晰推进。
			</p>
			<div className="fa-auth-login-visual" aria-hidden="true">
				<img alt="" src={loginVisualUrl} />
			</div>
		</section>
	);
}
