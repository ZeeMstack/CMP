"use client";

/** PILOT-PLAN-001B section 2/11: the Planning worksheet's shared date-window
 * context -- "Farm / Planning period selector" at the top of Overview, also
 * used by the Forecast and Capacity tabs so a manager's chosen window stays
 * consistent while switching tabs. Plain `type="date"` inputs, mirroring
 * the water-measurements page's own date-range convention -- no
 * `DateRangePicker` component exists in this codebase to reuse. */
export function PlanningPeriodSelector({
  start,
  end,
  onChange,
}: {
  start: string;
  end: string;
  onChange: (next: { start: string; end: string }) => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-wl-border bg-wl-surface-raised p-3">
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Period start</span>
        <input
          type="date"
          value={start}
          onChange={(e) => onChange({ start: e.target.value, end })}
          className="min-h-9 rounded-md border border-wl-border bg-wl-surface px-2 text-sm text-wl-text"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Period end</span>
        <input
          type="date"
          value={end}
          onChange={(e) => onChange({ start, end: e.target.value })}
          className="min-h-9 rounded-md border border-wl-border bg-wl-surface px-2 text-sm text-wl-text"
        />
      </label>
    </div>
  );
}
