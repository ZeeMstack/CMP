"use client";

import type { ReactNode } from "react";

export interface AllocationTotalsStat {
  label: string;
  value: string;
}

/** UX-OPS-001C shared primitive: the sticky capacity/allocated/remaining/
 * reconciliation rail for an allocation workspace (InterSalads, InterVines,
 * Leafy Production Transfer, Vines Production Transfer). Sits in
 * `SplitWorkspace`'s `rail` slot -- the same slot the Sowing summary uses --
 * so running totals stay visible beside a long source/destination editor
 * instead of scrolling away above it.
 *
 * Purely presentational: every stat is computed by the caller from the SAME
 * arithmetic helpers already backing validation (`sourceRemaining`,
 * `destinationAssignedCount`, ...), never a second copy of that math.
 * `blockers` lists every reason the primary action cannot proceed yet
 * (rendered as one `role="alert"` list so assistive tech announces a new
 * blocker); `children` is the caller's `StickyActionBar`, rendered last so
 * the action always reads directly under its blockers. */
export function AllocationSummaryRail({
  heading = "Summary",
  context,
  stats,
  hint,
  blockers,
  children,
}: {
  heading?: string;
  context?: ReactNode;
  stats: AllocationTotalsStat[];
  /** Neutral "what's still needed" guidance (e.g. "Add a destination") --
   * never styled or announced as an error, since an unfinished draft is a
   * normal state, not a failure. */
  hint?: string | null;
  blockers?: string[];
  children?: ReactNode;
}) {
  const visibleBlockers = (blockers ?? []).filter(Boolean);
  return (
    <section
      aria-label={heading}
      className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4"
    >
      <h2 className="text-sm font-semibold text-wl-text">{heading}</h2>
      {context}
      {stats.length > 0 && (
        <dl className="flex flex-col divide-y divide-wl-border text-sm">
          {stats.map((stat) => (
            <div key={stat.label} className="flex items-baseline justify-between gap-3 py-1.5">
              <dt className="text-wl-text-secondary">{stat.label}</dt>
              <dd className="font-semibold tabular-nums text-wl-text">{stat.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {hint && <p className="text-xs text-wl-text-secondary">{hint}</p>}
      {visibleBlockers.length > 0 && (
        <ul role="alert" className="flex flex-col gap-1 rounded-lg bg-wl-flag-bg px-3 py-2 text-xs font-medium text-wl-flag-fg">
          {visibleBlockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      )}
      {children}
    </section>
  );
}
