import type { FocusAgentAuditEvent } from "@focus-agent/web-sdk";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { formatAdminDate } from "@/features/admin-users/admin-user-utils";
import { useAdminAuditEvents } from "@/features/admin-users/use-admin-users";

import {
  AdminConsoleLayout,
  AdminErrorMessage,
} from "./admin-page-chrome";
import {
  AdminField,
  AdminFiltersRow,
  AdminPanelHeader,
} from "./admin-page-sections";
import { readAdminSearchParam, useAdminUrlSync } from "./admin-url-state";

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
  const [actorFilter, setActorFilter] = useState(() => readAdminSearchParam("actor"));
  const [resourceTypeFilter, setResourceTypeFilter] = useState(() => readAdminSearchParam("resource_type"));
  const [resourceIdFilter, setResourceIdFilter] = useState(() => readAdminSearchParam("resource_id"));
  const [decisionFilter, setDecisionFilter] = useState(() => readAdminSearchParam("decision"));
  const [selectedEventId, setSelectedEventId] = useState(() => readAdminSearchParam("event"));
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
  const urlFilters = useMemo(
    () => ({
      actor: actorFilter,
      decision: decisionFilter,
      event: selectedEventId,
      resource_id: resourceIdFilter,
      resource_type: resourceTypeFilter,
    }),
    [actorFilter, decisionFilter, resourceIdFilter, resourceTypeFilter, selectedEventId],
  );
  useAdminUrlSync(urlFilters);
  const auditQuery = useAdminAuditEvents(filters);
  const events = auditQuery.data?.items ?? [];
  const selectedEvent = events.find((event) => event.event_id === selectedEventId) ?? null;
  const highRiskCount = events.filter((event) =>
    ["users.password.reset", "users.roles", "users.status", "users.sessions.revoke"].some((prefix) =>
      event.action.includes(prefix),
    ),
  ).length;
  const deniedCount = events.filter((event) => decisionTone(event.decision) === "danger").length;

  return (
    <AdminConsoleLayout
      active="audit"
      title={isChineseUi ? "审计事件" : "Audit Events"}
      summary={
        isChineseUi
          ? "按操作者、资源和授权决策追踪管理员操作，并在右侧查看事件详情。"
          : "Track administrator actions by actor, resource, and authorization decision, with detail in the drawer."
      }
      drawer={
        selectedEvent ? (
          <AuditEventDrawer
            event={selectedEvent}
            isChineseUi={isChineseUi}
            locale={locale}
            onClose={() => setSelectedEventId("")}
          />
        ) : null
      }
      drawerLabel={isChineseUi ? "审计详情" : "Audit detail"}
    >
      <section className="fa-admin-panel fa-admin-primary-panel">
        <AdminPanelHeader
          eyebrow={isChineseUi ? "Filters" : "Filters"}
          status={
            auditQuery.isLoading
              ? "loading"
              : `${events.length} rows · ${highRiskCount} high-risk · ${deniedCount} denied`
          }
          title={isChineseUi ? "审计检索" : "Audit Search"}
        />
        <AdminFiltersRow className="fa-observability-filters fa-admin-filters is-four">
          <AdminField label={isChineseUi ? "操作者" : "Actor"}>
            <input value={actorFilter} onChange={(event) => setActorFilter(event.target.value)} />
          </AdminField>
          <AdminField label={isChineseUi ? "资源类型" : "Resource type"}>
            <input value={resourceTypeFilter} onChange={(event) => setResourceTypeFilter(event.target.value)} />
          </AdminField>
          <AdminField label={isChineseUi ? "资源 ID" : "Resource ID"}>
            <input value={resourceIdFilter} onChange={(event) => setResourceIdFilter(event.target.value)} />
          </AdminField>
          <AdminField label={isChineseUi ? "决策" : "Decision"}>
            <select value={decisionFilter} onChange={(event) => setDecisionFilter(event.target.value)}>
              <option value="">{isChineseUi ? "全部" : "All"}</option>
              <option value="allow">allow</option>
              <option value="deny">deny</option>
            </select>
          </AdminField>
        </AdminFiltersRow>
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
                <th>{isChineseUi ? "操作" : "Action"}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr className={selectedEventId === event.event_id ? "is-selected" : undefined} key={event.event_id}>
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
                    <ResourceCell event={event} />
                  </td>
                  <td>
                    <span className={`fa-observability-pill is-${decisionTone(event.decision)}`}>
                      {event.decision}
                    </span>
                  </td>
                  <td>
                    <button
                      className="fa-admin-row-link fa-admin-session-button"
                      type="button"
                      onClick={() => setSelectedEventId(event.event_id)}
                    >
                      {isChineseUi ? "详情" : "Details"}
                    </button>
                  </td>
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
    </AdminConsoleLayout>
  );
}

function ResourceCell({ event }: { event: FocusAgentAuditEvent }) {
  const isUserResource = event.resource_type === "user" && Boolean(event.resource_id);

  return (
    <div className="fa-admin-identity-cell">
      <strong>{event.resource_type}</strong>
      {isUserResource ? (
        <Link
          className="fa-admin-row-link"
          params={{ userId: event.resource_id ?? "" }}
          to="/admin/users/$userId"
        >
          {event.resource_id}
        </Link>
      ) : (
        <span>{event.resource_id || "-"}</span>
      )}
    </div>
  );
}

function AuditEventDrawer({
  event,
  isChineseUi,
  locale,
  onClose,
}: {
  event: FocusAgentAuditEvent;
  isChineseUi: boolean;
  locale: string;
  onClose: () => void;
}) {
  return (
    <div className="fa-admin-drawer-shell">
      <header className="fa-admin-drawer-header">
        <div>
          <span>{isChineseUi ? "审计详情" : "Audit detail"}</span>
          <h2>{event.action}</h2>
          <p>{formatAdminDate(event.created_at, locale)}</p>
        </div>
        <button className="fa-admin-icon-button" type="button" onClick={onClose} aria-label={isChineseUi ? "关闭审计详情" : "Close audit detail"}>
          x
        </button>
      </header>

      <div className="fa-admin-drawer-body">
        <section className="fa-admin-panel">
          <AdminPanelHeader
            eyebrow={isChineseUi ? "Event" : "Event"}
            status={<span className={`fa-observability-pill is-${decisionTone(event.decision)}`}>{event.decision}</span>}
            title={isChineseUi ? "事件概览" : "Event overview"}
          />
          <dl className="fa-admin-detail-list">
            <div>
              <dt>{isChineseUi ? "操作者" : "Actor"}</dt>
              <dd>{event.actor_user_id || "-"}</dd>
            </div>
            <div>
              <dt>{isChineseUi ? "资源" : "Resource"}</dt>
              <dd>
                {event.resource_type}
                {event.resource_id ? ` / ${event.resource_id}` : ""}
              </dd>
            </div>
            <div>
              <dt>{isChineseUi ? "原因" : "Reason"}</dt>
              <dd>{event.reason || "-"}</dd>
            </div>
            <div>
              <dt>Request ID</dt>
              <dd>{event.request_id || "-"}</dd>
            </div>
          </dl>
          {event.resource_type === "user" && event.resource_id ? (
            <Link
              className="fa-observability-preset is-primary"
              params={{ userId: event.resource_id }}
              to="/admin/users/$userId"
            >
              {isChineseUi ? "打开用户" : "Open user"}
            </Link>
          ) : null}
        </section>

        <section className="fa-admin-panel">
          <AdminPanelHeader
            eyebrow={isChineseUi ? "Metadata" : "Metadata"}
            title={isChineseUi ? "事件元数据" : "Event metadata"}
          />
          <pre className="fa-admin-json-block">{JSON.stringify(event.metadata ?? {}, null, 2)}</pre>
        </section>
      </div>
    </div>
  );
}
