"use client";

import { ReconciliationSummary } from "@/components/processing/ReconciliationSummary";
import type { PackingEventRead } from "@/lib/api/client";

/** POSTHARVEST-OPS-001G: Packing History -- every recorded Packing Event,
 * its reconciliation (using the server-computed `total_input_weight_kg`),
 * and the Finished Goods Lot it produced. Read-only -- Packing has no
 * correction command in this ticket's scope. */
export function PackingHistoryPanel({ events, isLoading }: { events: PackingEventRead[]; isLoading: boolean }) {
  if (isLoading) {
    return <p className="text-sm text-ink-muted">Loading Packing history…</p>;
  }
  if (events.length === 0) {
    return <p className="text-sm text-ink-muted">No Packing events recorded yet.</p>;
  }

  const sorted = [...events].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <ul className="flex flex-col gap-4">
      {sorted.map((event) => (
        <li key={event.id} className="flex flex-col gap-3 rounded-lg border border-border-subtle p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold text-ink">
              {event.finished_goods_lot.code} — {event.crop.common_name}
              {event.variety ? ` / ${event.variety.name}` : ""}
            </span>
            <span className="text-xs text-ink-muted">{new Date(event.effective_time).toLocaleString()}</span>
          </div>
          <ReconciliationSummary
            inputLabel="Total consumed input"
            inputValue={Number(event.total_input_weight_kg)}
            unit="kg"
            parts={[
              { label: "Packed output", value: Number(event.packed_output_weight_kg) },
              { label: "Process loss", value: Number(event.process_loss_weight_kg) },
              { label: "Rejected", value: Number(event.rejected_weight_kg) },
            ]}
          />
          {event.note && <p className="text-xs text-ink-muted">{event.note}</p>}
          <ul className="flex flex-col gap-2 divide-y divide-border-subtle text-sm">
            {event.input_lines.map((line) => (
              <li key={line.id} className="pt-2 first:pt-0">
                <span className="font-medium text-ink">{line.graded_produce_lot_code}</span>{" "}
                <span className="text-ink-muted">
                  — consumed {line.consumed_weight_kg} kg
                  {line.consumed_whole_unit_count != null ? ` / ${line.consumed_whole_unit_count} units` : ""}
                </span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
