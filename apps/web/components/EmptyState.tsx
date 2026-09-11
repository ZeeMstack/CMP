import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div
      role="status"
      className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-wl-border bg-wl-surface-raised px-6 py-8 text-center"
    >
      <p className="text-base font-medium text-wl-text">{title}</p>
      {description && <p className="max-w-prose text-sm text-wl-text-secondary">{description}</p>}
      {action}
    </div>
  );
}
