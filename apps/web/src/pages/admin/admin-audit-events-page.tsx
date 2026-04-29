import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { formatAdminDate } from "@/features/admin-users/admin-user-utils";
import { useAdminAuditEvents } from "@/features/admin-users/use-admin-users";

import {
  AdminAccessGate,
  AdminErrorMessage,
  AdminPageHeading,
} from "./admin-page-chrome";

function decisionTone(decision: string): "success" | "warning" | "danger" | "neutral" {
  const normalized = decision.toLowerCase();
  if (normalized === "allow" || normalized === "allowed" || normalized === "success") return "success";
  if (normalized === "deny" || normalized === "denied" || normalized === "blocked") return "danger";
  if (normalized === "warn" || normalized === "warning") return "warning";
  return "neutral";
}

export function AdminAuditEventsPage() {
  const { isChineseUi } = useShellUi();
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const [actorFilter, setActorFilter] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [resourceIdFilter, setResourceIdFilter] = useState("");
  const [decisionFilter, setDecisionFilter] = useState("");
  const filters = useMemo(
    () => ({
      actor_user_id: actorFilter.trim() || undefined,
      resource_type: resourceTypeFilter.trim() || undefined,
      resource_id: resourceIdFilter.trim() || undefined,
      decision: decisionFilter.trim() || undefined,
      limit: 100,
      offset: 0,
    }),
    [actorFilter, decisionFilter, resourceIdFilter, resourceTypeFilter],
  );
  const auditQuery = useAdminAuditEvents(filters);
  const events = auditQuery.data?.items ?? [];

  return (
    <AdminAccessGate>
      <div className="fa-admin-layout">
        <AdminPageHeading
          active="audit"
          title={isChineseUi ? "审计事件" : "Audit Events"}
          summary={
            isChineseUi
              ? "按操作者、资源和授权决策追踪管理员操作。"
              : "Track administrator actions by actor, resource, and authorization decision."
          }
          side={
            <div className="fa-admin-stat-stack">
              <div className="fa-trajectory-overview-runtime">
                <span>{isChineseUi ? "事件数" : "Events"}</span>
                <strong>{auditQuery.data?.count ?? events.length}</strong>
              </div>
            </div>
          }
        />

        <section className="fa-admin-panel">
          <div className="fa-observability-panel-header">
            <div>
              <strong>{isChineseUi ? "Filters" : "Filters"}</strong>
              <h2>{isChineseUi ? "审计检索" : "Audit Search"}</h2>
            </div>
            <span>{auditQuery.isLoading ? "loading" : `${events.length} rows`}</span>
          </div>
          <div className="fa-observability-filters fa-admin-filters is-four">
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "操作者" : "Actor"}</span>
              <input value={actorFilter} onChange={(event) => setActorFilter(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "资源类型" : "Resource type"}</span>
              <input value={resourceTypeFilter} onChange={(event) => setResourceTypeFilter(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "资源 ID" : "Resource ID"}</span>
              <input value={resourceIdFilter} onChange={(event) => setResourceIdFilter(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "决策" : "Decision"}</span>
              <select value={decisionFilter} onChange={(event) => setDecisionFilter(event.target.value)}>
                <option value="">{isChineseUi ? "全部" : "All"}</option>
                <option value="allow">allow</option>
                <option value="deny">deny</option>
              </select>
            </label>
          </div>
          {auditQuery.error ? (
            <AdminErrorMessage error={auditQuery.error} fallback="Failed to load audit events." />
          ) : null}
          <div className="fa-admin-table-scroll">
            <table className="fa-admin-table">
              <thead>
                <tr>
                  <th>{isChineseUi ? "时间" : "Time"}</th>
                  <th>{isChineseUi ? "操作者" : "Actor"}</th>
                  <th>{isChineseUi ? "动作" : "Action"}</th>
                  <th>{isChineseUi ? "资源" : "Resource"}</th>
                  <th>{isChineseUi ? "决策" : "Decision"}</th>
                  <th>{isChineseUi ? "原因" : "Reason"}</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.event_id}>
                    <td>{formatAdminDate(event.created_at, locale)}</td>
                    <td>
                      {event.actor_user_id ? (
                        <Link
                          className="fa-admin-row-link"
                          params={{ userId: event.actor_user_id }}
                          to="/admin/users/$userId"
                        >
                          {event.actor_user_id}
                        </Link>
                      ) : "-"}
                    </td>
                    <td>{event.action}</td>
                    <td>
                      <div className="fa-admin-identity-cell">
                        <strong>{event.resource_type}</strong>
                        <span>{event.resource_id || "-"}</span>
                      </div>
                    </td>
                    <td>
                      <span className={`fa-observability-pill is-${decisionTone(event.decision)}`}>
                        {event.decision}
                      </span>
                    </td>
                    <td>{event.reason || "-"}</td>
                  </tr>
                ))}
                {!events.length && !auditQuery.isLoading ? (
                  <tr>
                    <td colSpan={6}>
                      <div className="fa-observability-empty is-compact">
                        {isChineseUi ? "没有匹配的审计事件。" : "No audit events match these filters."}
                      </div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </AdminAccessGate>
  );
}
