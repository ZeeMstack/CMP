"use client";

import { ReconciliationSummary } from "@/components/processing/ReconciliationSummary";
import type { GradingEventRead } from "@/lib/api/client";

/** POSTHARVEST-OPS-001G: Grading History -- every recorded Grading Event,
 * its reconciliation (using the server-computed `processed_weight_kg`, not
 * a client-side re-sum), and the Graded Produce Lots it produced. Read-only
 * -- Grading has no correction command in this ticket's scope (unlike
 * Harvest's line-level correction). */
export function GradingHistoryPanel({ events, isLoading }: { events: GradingEventRead[]; isLoading: boolean }) {
  if (isLoading) {
    return <p className="text-sm text-ink-muted">Loading Grading history…</p>;
  }
  if (events.length === 0) {
    return <p className="text-sm text-ink-muted">No Grading events recorded yet.</p>;
  }

  const sorted = [...events].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <ul className="flex flex-col gap-4">
      {sorted.map((event) => (
        <li key={event.id} className="flex flex-col gap-3 rounded-lg border border-border-subtle p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold text-ink">Source {event.source_produce_lot_code}</span>
            <span className="text-xs text-ink-muted">{new Date(event.effective_time).toLocaleString()}</span>
          </div>
          <ReconciliationSummary
            inputLabel="Input presented"
            inputValue={Number(event.input_presented_weight_kg)}
            unit="kg"
            parts={[
              { label: "Rejected", value: Number(event.rejected_weight_kg) },
              { label: "Loss", value: Number(event.loss_weight_kg) },
              { label: "Sample", value: Number(event.sample_weight_kg) },
              { label: "Remainder", value: Number(event.remainder_weight_kg) },
              { label: "Graded outputs", value: Number(event.processed_weight_kg) },
            ]}
          />
          {event.note && <p className="text-xs text-ink-muted">{event.note}</p>}
          <ul className="flex flex-col gap-2 divide-y divide-border-subtle text-sm">
            {event.outputs.map((output) => (
              <li key={output.id} className="pt-2 first:pt-0">
                <span className="font-medium text-ink">{output.code}</span>{" "}
                <span className="text-ink-muted">
                  — {output.original_received_weight_kg} kg
                  {output.original_received_whole_unit_count != null ? ` / ${output.original_received_whole_unit_count} units` : ""}
                </span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
