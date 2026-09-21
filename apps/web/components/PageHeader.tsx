import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  compact = false,
}: {
  title: string;
  description?: ReactNode;
  breadcrumbs?: ReactNode;
  actions?: ReactNode;
  /** UX-OPS-001A: a shorter header (target ~72-104px including breadcrumb)
   * for operational screens where the routine work needs the vertical
   * space. Defaults to false so every existing route keeps its current
   * header exactly as-is. */
  compact?: boolean;
}) {
  return (
    <div className={`flex flex-col border-b border-wl-border ${compact ? "mb-4 gap-1.5 pb-3" : "mb-6 gap-3 pb-5"}`}>
      {breadcrumbs}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h1
            className={
              compact
                ? "font-serif text-lg font-semibold leading-tight tracking-[-0.01em] text-wl-text"
                : "font-serif text-[28px] font-semibold leading-[1.15] tracking-[-0.02em] text-wl-text md:text-[32px]"
            }
          >
            {title}
          </h1>
          {description && <p className="max-w-[65ch] text-sm text-wl-text-secondary">{description}</p>}
        </div>
        {actions && <div className="flex min-w-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
