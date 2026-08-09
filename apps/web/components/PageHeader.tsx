import type { ReactNode } from "react";

export function PageHeader({
  title,
  breadcrumbs,
  actions,
}: {
  title: string;
  breadcrumbs?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-2 border-b border-border-subtle pb-4">
      {breadcrumbs}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {actions}
      </div>
    </div>
  );
}
