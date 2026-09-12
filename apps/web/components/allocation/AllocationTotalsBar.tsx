"use client";

/** PILOT-UX-002A: shared compact running-totals strip for the Production
 * Transfer and InterSalads allocation workspaces. Purely presentational --
 * every number is computed by the caller from the SAME arithmetic helpers
 * already backing validation (`sourceRemaining`, `destinationAssignedCount`,
 * etc. in `lib/validation/*`), never a second, independently-maintained
 * copy of that math. Sticky so source/destination totals stay visible while
 * scrolling a long draft, without needing a giant footer. */
export interface AllocationTotalsStat {
  label: string;
  value: string;
}

export function AllocationTotalsBar({ stats, warning }: { stats: AllocationTotalsStat[]; warning?: string | null }) {
  return (
    <div className="sticky top-0 z-10 flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border border-wl-border bg-wl-surface-raised px-4 py-2 text-sm shadow-sm">
      {stats.map((stat) => (
        <div key={stat.label} className="flex items-baseline gap-1.5 whitespace-nowrap">
          <dt className="text-xs text-wl-text-secondary">{stat.label}</dt>
          <dd className="font-semibold text-wl-text">{stat.value}</dd>
        </div>
      ))}
      {warning && (
        <p role="alert" className="ml-auto text-xs font-medium text-danger-700">
          {warning}
        </p>
      )}
    </div>
  );
}
