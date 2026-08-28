"use client";

import { useState } from "react";

import { ReconciliationSummary } from "@/components/processing/ReconciliationSummary";
import { ReversalConfirmForm } from "@/components/processing/ReversalConfirmForm";
import { Button } from "@/components/ui/Button";
import type { PackingEventRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { usePackingReversalEvent, useReversePackingEvent } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** POSTHARVEST-OPS-001H: one Packing History row -- shows the "Reverse"
 * action (with its mandatory-reason confirmation) while the event has not
 * yet been reversed, and the reversal's own reason/note/neutralized
 * quantity once it has. Whole-event reversal only -- never a field-by-field
 * correction, and the original event/lot are never hidden or rewritten. */
function PackingHistoryItem({ farmId, event }: { farmId: string; event: PackingEventRead }) {
  const [confirming, setConfirming] = useState(false);
  const reversalQuery = usePackingReversalEvent(farmId, event.id);
  const reverseMutation = useReversePackingEvent(farmId);
  const reversal = reversalQuery.data;

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-serif text-sm font-semibold text-ink">
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

      {reversal ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm">
          <p className="font-medium text-ink">
            Reversed {new Date(reversal.effective_time).toLocaleString()} — {reversal.reason_code}
          </p>
          {reversal.note && <p className="text-ink-muted">{reversal.note}</p>}
        </div>
      ) : confirming ? (
        <ReversalConfirmForm
          title="Reverse this Packing event?"
          description="Restores every source Graded Produce Lot's balance and neutralizes this Finished Goods Lot's opening quantity. Blocked if this lot has already been dispatched or placed into cold storage. The original event stays visible in history."
          isSubmitting={reverseMutation.isPending}
          serverError={reverseMutation.isError ? errorMessage(reverseMutation.error) : null}
          onCancel={() => setConfirming(false)}
          onConfirm={(payload) => {
            reverseMutation.mutate(
              {
                packingEventId: event.id, finishedGoodsLotId: event.finished_goods_lot.id,
                payload: { client_command_id: crypto.randomUUID(), effective_time: new Date().toISOString(), ...payload },
              },
              { onSuccess: () => setConfirming(false) },
            );
          }}
        />
      ) : (
        !reversalQuery.isLoading && (
          <Button type="button" variant="secondary" className="self-start" onClick={() => setConfirming(true)}>
            Reverse
          </Button>
        )
      )}
    </li>
  );
}

/** POSTHARVEST-OPS-001G/001H: Packing History -- every recorded Packing
 * Event, its reconciliation (using the server-computed
 * `total_input_weight_kg`), the Finished Goods Lot it produced, and (001H)
 * whole-event reversal. */
export function PackingHistoryPanel({
  farmId, events, isLoading,
}: {
  farmId: string;
  events: PackingEventRead[];
  isLoading: boolean;
}) {
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
        <PackingHistoryItem key={event.id} farmId={farmId} event={event} />
      ))}
    </ul>
  );
}
