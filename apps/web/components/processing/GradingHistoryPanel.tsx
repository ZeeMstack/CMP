"use client";

import { useState } from "react";

import { ReconciliationSummary } from "@/components/processing/ReconciliationSummary";
import { ReversalConfirmForm } from "@/components/processing/ReversalConfirmForm";
import type { GradingEventRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useGradingReversalEvent, useReverseGradingEvent } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** POSTHARVEST-OPS-001H: one Grading History row -- shows the "Reverse"
 * action (with its mandatory-reason confirmation) while the event has not
 * yet been reversed, and the reversal's own reason/note/restored quantity
 * once it has. Whole-event reversal only -- never a field-by-field
 * correction, and the original event/outputs are never hidden or rewritten. */
function GradingHistoryItem({ farmId, event }: { farmId: string; event: GradingEventRead }) {
  const [confirming, setConfirming] = useState(false);
  const reversalQuery = useGradingReversalEvent(farmId, event.id);
  const reverseMutation = useReverseGradingEvent(farmId);
  const reversal = reversalQuery.data;

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border-subtle p-3">
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

      {reversal ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm">
          <p className="font-medium text-ink">
            Reversed {new Date(reversal.effective_time).toLocaleString()} — {reversal.reason_code}
          </p>
          {reversal.note && <p className="text-ink-muted">{reversal.note}</p>}
        </div>
      ) : confirming ? (
        <ReversalConfirmForm
          title="Reverse this Grading event?"
          description="Restores the source lot's balance and zeroes every output lot produced by this event. The original event stays visible in history. Enter a new, correct Grading transaction afterward."
          isSubmitting={reverseMutation.isPending}
          serverError={reverseMutation.isError ? errorMessage(reverseMutation.error) : null}
          onCancel={() => setConfirming(false)}
          onConfirm={(payload) => {
            reverseMutation.mutate(
              {
                gradingEventId: event.id, sourceHarvestedProduceLotId: event.source_harvested_produce_lot_id,
                payload: { client_command_id: crypto.randomUUID(), effective_time: new Date().toISOString(), ...payload },
              },
              { onSuccess: () => setConfirming(false) },
            );
          }}
        />
      ) : (
        !reversalQuery.isLoading && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="min-h-11 self-start rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Reverse
          </button>
        )
      )}
    </li>
  );
}

/** POSTHARVEST-OPS-001G/001H: Grading History -- every recorded Grading
 * Event, its reconciliation (using the server-computed
 * `processed_weight_kg`, not a client-side re-sum), the Graded Produce Lots
 * it produced, and (001H) whole-event reversal. */
export function GradingHistoryPanel({
  farmId, events, isLoading,
}: {
  farmId: string;
  events: GradingEventRead[];
  isLoading: boolean;
}) {
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
        <GradingHistoryItem key={event.id} farmId={farmId} event={event} />
      ))}
    </ul>
  );
}
