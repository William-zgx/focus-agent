import { Link } from "@tanstack/react-router";

import { EmptyState } from "@/shared/ui/primitives";

export function NotFoundPage() {
	const isChineseUi = navigator?.language.toLowerCase().startsWith("zh");

	return (
		<div className="fa-route-state">
			<EmptyState
				action={
					<Link className="fa-route-state-link" to="/">
						{isChineseUi ? "返回首页" : "Go back home"}
					</Link>
				}
				className="fa-route-state-card"
				title={isChineseUi ? "页面不存在" : "Page not found"}
			/>
		</div>
	);
}
