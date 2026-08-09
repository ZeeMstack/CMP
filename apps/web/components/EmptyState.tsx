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
      className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border-subtle bg-surface px-6 py-12 text-center"
    >
      <p className="text-base font-medium text-ink">{title}</p>
      {description && <p className="max-w-prose text-sm text-ink-muted">{description}</p>}
      {action}
    </div>
  );
}
