import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function AccountSessionsPage() {
  const { client, ready } = useFocusAgent();
  const queryClient = useQueryClient();
  const sessions = useQuery({
    queryKey: queryKeys.mySessions,
    queryFn: () => client.listMySessions(),
    enabled: ready,
  });
  const revokeSession = useMutation({
    mutationFn: (sessionId: string) => client.revokeSession(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.mySessions });
    },
  });
  const items = sessions.data?.items ?? [];

  return (
    <div className="fa-account-layout">
      <section className="fa-account-panel">
        <div className="fa-account-header">
          <p>账户</p>
          <h1>会话管理</h1>
        </div>
        <nav aria-label="账户页面导航" className="fa-account-nav">
          <Link className="fa-route-state-link" to="/auth">
            返回入口
          </Link>
          <Link className="fa-route-state-link" to="/account/profile">
            个人资料
          </Link>
          <Link className="fa-route-state-link" to="/account/security">
            安全设置
          </Link>
        </nav>

        {sessions.error ? (
          <div className="fa-inline-notice is-danger">
            {sessions.error instanceof Error ? sessions.error.message : "会话加载失败。"}
          </div>
        ) : null}
        {revokeSession.error ? (
          <div className="fa-inline-notice is-danger">
            {revokeSession.error instanceof Error ? revokeSession.error.message : "会话撤销失败。"}
          </div>
        ) : null}

        {sessions.isLoading ? (
          <div className="fa-inline-notice">会话列表加载中...</div>
        ) : items.length ? (
          <div className="fa-account-session-list">
            {items.map((session) => (
              <article className="fa-account-session-row" key={session.session_id}>
                <div>
                  <strong>{session.current ? "当前会话" : session.session_id}</strong>
                  <span>{session.user_agent || "未知客户端"}</span>
                  <small>
                    上次活跃 {formatDateTime(session.last_seen_at)} · 过期 {formatDateTime(session.expires_at)}
                  </small>
                </div>
                <button
                  className="fa-auth-button"
                  disabled={Boolean(session.revoked_at) || session.current || revokeSession.isPending}
                  onClick={() => revokeSession.mutate(session.session_id)}
                  type="button"
                >
                  {session.revoked_at ? "已撤销" : "撤销"}
                </button>
              </article>
            ))}
          </div>
        ) : (
          <div className="fa-inline-notice">暂无会话。</div>
        )}
      </section>
    </div>
  );
}
