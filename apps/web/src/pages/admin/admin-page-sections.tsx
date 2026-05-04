import type { PropsWithChildren, ReactNode } from "react";

export function AdminPanelHeader({
  eyebrow,
  title,
  status,
}: {
  eyebrow: string;
  title: string;
  status?: ReactNode;
}) {
  return (
    <div className="fa-observability-panel-header">
      <div>
        <strong>{eyebrow}</strong>
        <h2>{title}</h2>
      </div>
      <span>{status}</span>
    </div>
  );
}

export function AdminField({
  label,
  children,
}: PropsWithChildren<{ label: ReactNode }>) {
  return (
    // biome-ignore lint/a11y/noLabelWithoutControl: concrete callers always pass an input/select/textarea as children.
    <label className="fa-observability-filter">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function AdminFiltersRow({
  children,
  className = "fa-observability-filters fa-admin-filters",
}: PropsWithChildren<{ className?: string }>) {
  return <div className={className}>{children}</div>;
}
