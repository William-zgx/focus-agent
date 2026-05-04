import { Link } from "@tanstack/react-router";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function AccountProfilePage() {
  const { principal } = useFocusAgent();
  const user = principal?.user;
  const displayName = user?.display_name || user?.username || principal?.user_id || "Current user";

  return (
    <div className="fa-account-layout">
      <section className="fa-account-panel">
        <div className="fa-account-header">
          <p>账户</p>
          <h1>个人资料</h1>
        </div>
        <div className="fa-account-summary">
          <div>
            <span>显示名</span>
            <strong>{displayName}</strong>
          </div>
          <div>
            <span>用户名</span>
            <strong>{user?.username ?? principal?.user_id ?? "-"}</strong>
          </div>
          <div>
            <span>用户 ID</span>
            <strong>{principal?.user_id ?? "-"}</strong>
          </div>
          <div>
            <span>租户</span>
            <strong>{principal?.tenant_id ?? user?.tenant_id ?? "default"}</strong>
          </div>
          <div>
            <span>状态</span>
            <strong>{user?.status ?? "active"}</strong>
          </div>
          <div>
            <span>角色</span>
            <strong>{(principal?.roles?.length ? principal.roles : user?.roles ?? []).join(", ") || "member"}</strong>
          </div>
        </div>
        <nav aria-label="账户页面导航" className="fa-account-nav">
          <Link className="fa-route-state-link" to="/auth">
            返回入口
          </Link>
          <Link className="fa-route-state-link" to="/account/security">
            安全设置
          </Link>
          <Link className="fa-route-state-link" to="/account/sessions">
            会话管理
          </Link>
        </nav>
      </section>
    </div>
  );
}
