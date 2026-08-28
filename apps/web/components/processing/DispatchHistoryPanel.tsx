"use client";

import type { DispatchEventRead } from "@/lib/api/client";

/** PILOT-READY-001: the smallest usable Dispatch verification/read state --
 * a flat, most-recent-first list of this Farm's Dispatch events so an
 * operator can confirm what was recorded (code, lines, temperature).
 * Deliberately not a richer history feature (filtering, per-lot
 * drill-down beyond what the API returns) -- that is UI-OPT-001 scope. */
export function DispatchHistoryPanel({
  events,
  isLoading,
}: {
  events: DispatchEventRead[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="text-sm text-ink-muted">Loading dispatch history…</p>;
  }
  if (events.length === 0) {
    return <p className="text-sm text-ink-muted">No dispatches recorded yet in this Farm.</p>;
  }

  const sorted = [...events].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <ul className="flex flex-col gap-3">
      {sorted.map((event) => (
        <li key={event.id} className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-serif text-sm font-semibold text-ink">{event.code}</span>
            <span className="text-xs text-ink-muted">{new Date(event.effective_time).toLocaleString()}</span>
          </div>
          <span className="text-xs text-ink-muted">
            {event.total_dispatched_weight_kg} kg / {event.total_dispatched_package_count} packages across{" "}
            {event.lines.length} lot{event.lines.length === 1 ? "" : "s"}
          </span>
          {/* Vehicle/dispatch-level reading, shown once per event -- never
              per line below -- same rationale as `DispatchForm`'s own
              review-step temperature block. */}
          <span className="w-fit rounded-md border border-border-subtle bg-surface-subtle px-2 py-1 text-xs text-ink">
            Temperature: {event.dispatch_temperature_c != null ? `${event.dispatch_temperature_c} °C` : "not recorded"}
          </span>
          {event.external_reference && <span className="text-xs text-ink-muted">Reference: {event.external_reference}</span>}
          <ul className="mt-1 flex flex-col gap-0.5">
            {event.lines.map((line) => (
              <li key={line.id} className="text-xs text-ink-muted">
                {line.finished_goods_lot_code} — {line.dispatched_weight_kg} kg / {line.dispatched_package_count} pkg
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
