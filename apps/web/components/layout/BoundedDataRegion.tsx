import type { ReactNode } from "react";

/** UX-OPS-001A shared primitive: a repeated-row editor/list region bounded
 * to roughly 6-8 visible rows with its own internal scroll, so a long
 * allocation never lengthens the page itself. `heading`, when given, stays
 * pinned while the rows scroll beneath it. Purely presentational -- it
 * neither owns nor limits the underlying data, only how many rows are
 * visible before the operator scrolls this one bounded region. */
export function BoundedDataRegion({ heading, children }: { heading?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-wl-border">
      {heading && (
        <div className="sticky top-0 z-[1] rounded-t-lg border-b border-wl-border bg-wl-surface-raised px-3 py-1.5">
          {heading}
        </div>
      )}
      <div className="max-h-[26rem] overflow-y-auto">{children}</div>
    </div>
  );
}
