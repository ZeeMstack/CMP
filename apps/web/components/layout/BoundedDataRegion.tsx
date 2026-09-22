import type { ReactNode } from "react";

/** UX-OPS-001A/R1 shared primitive: a repeated-row editor/list region
 * bounded to roughly 6-8 visible rows with its own internal scroll, so a
 * long allocation never lengthens the page itself. `heading`, when given,
 * stays pinned while the rows scroll beneath it; `footer`, when given, sits
 * outside the scrolling area entirely so a running total stays visible
 * without scrolling away with the rows. `label` names the region for
 * assistive tech (rendered as `role="region"`/`aria-label`) -- omit it only
 * when an ancestor already labels this same content. Purely
 * presentational -- it neither owns nor limits the underlying data, only
 * how many rows are visible before the operator scrolls this one bounded
 * region. */
export function BoundedDataRegion({
  heading,
  footer,
  label,
  children,
}: {
  heading?: ReactNode;
  footer?: ReactNode;
  label?: string;
  children: ReactNode;
}) {
  return (
    <div
      role={label ? "region" : undefined}
      aria-label={label}
      className="rounded-lg border border-wl-border"
    >
      {heading && (
        <div className="sticky top-0 z-[1] rounded-t-lg border-b border-wl-border bg-wl-surface-raised px-3 py-1.5">
          {heading}
        </div>
      )}
      <div className="max-h-[26rem] overflow-y-auto">{children}</div>
      {footer && (
        <div className="rounded-b-lg border-t border-wl-border bg-wl-surface-raised px-3 py-1.5">{footer}</div>
      )}
    </div>
  );
}
