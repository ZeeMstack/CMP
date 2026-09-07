"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { QualityActionPanel } from "@/components/store-inventory/QualityActionPanel";
import type { QualityWorkQueueRowRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useApplyQualityDispositionToPartialQuantity, useCorrectQualityDisposition,
  useCorrectQualityDispositionForPartialQuantity, useQualityWorkQueue, useRecordQualityDisposition,
} from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** UX-only mirror of the backend's frozen state machine (docs/domain/
 * STORE_INVENTORY_MODEL.md §11) -- purely which action buttons to offer.
 * The backend independently, authoritatively re-validates every command;
 * this table never substitutes for that. */
const ORDINARY_ACTIONS: Record<string, string[]> = {
  RECEIVED_QUARANTINED: ["RELEASED", "HELD", "REJECTED"],
  RELEASED: ["HELD", "REJECTED"],
  HELD: ["HOLD_RELEASED", "REJECTED"],
  HOLD_RELEASED: ["HELD", "REJECTED"],
  REJECTED: [],
};

type Selection =
  | { cohortId: string; kind: "ORDINARY"; disposition: string }
  | { cohortId: string; kind: "PARTIAL" }
  | { cohortId: string; kind: "CORRECT" }
  | { cohortId: string; kind: "PARTIAL_CORRECT" };

/** STORE-INV-002A.2: the Quality work queue -- Release / Hold / Reject /
 * Hold-Release, "Apply disposition to part of quantity" (never "Split
 * Cohort"), "Correct decision", and "Correct decision for part of
 * quantity" (CTO closure pass §3 -- e.g. un-rejecting part of a REJECTED
 * cohort; never exposed for the automatic opening RECEIVED_QUARANTINED
 * fact, and never for implicit RELEASED with no human decision yet). Every
 * correction command carries the row's own `current_event_id` as
 * `target_event_id`, sourced from this same work-queue read -- if the
 * decision has changed since the row was fetched, the backend rejects the
 * command as a stale-target conflict rather than silently reinterpreting
 * it (CTO closure pass §2). */
export default function StoreInventoryQualityPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const queueQuery = useQualityWorkQueue();
  const [selection, setSelection] = useState<Selection | null>(null);
  const [error, setError] = useState<AppError | null>(null);

  const dispositionMutation = useRecordQualityDisposition();
  const partialMutation = useApplyQualityDispositionToPartialQuantity();
  const correctMutation = useCorrectQualityDisposition();
  const partialCorrectMutation = useCorrectQualityDispositionForPartialQuantity();

  const rows = [...(queueQuery.data ?? [])].sort(
    (a, b) => new Date(b.receipt_received_at).getTime() - new Date(a.receipt_received_at).getTime(),
  );

  function close() {
    setSelection(null);
    setError(null);
  }

  return (
    <div>
      <PageHeader
        title="Quality"
        description="Release, Hold, Reject, and correct Quality decisions for received material."
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Store & Inventory", href: `/farms/${farmId}/store-inventory` },
              { label: "Quality" },
            ]}
          />
        }
      />

      {queueQuery.isLoading ? (
        <p className="text-sm text-wl-text-secondary">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-wl-text">Nothing currently needs Quality attention.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((row: QualityWorkQueueRowRead) => {
            const actions = ORDINARY_ACTIONS[row.current_state] ?? [];
            // A human decision to correct only exists once at least one
            // event has been recorded -- implicit RELEASED (zero events)
            // has nothing to correct, exactly like RECEIVED_QUARANTINED.
            const canCorrect = row.current_event_id !== null && row.current_state !== "RECEIVED_QUARANTINED";
            const isRestrictedNow = selection?.cohortId === row.inventory_quantity_cohort_id;
            return (
              <li key={row.inventory_quantity_cohort_id} className="rounded-xl border border-wl-border bg-wl-surface-raised p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-medium text-wl-text">{row.item_name}</p>
                    <p className="text-xs text-wl-text-tertiary">
                      {row.balance} · {row.current_state}
                      {row.manufacturer_lot_reference ? ` · Lot ${row.manufacturer_lot_reference}` : ""}
                      {row.expiry_date ? ` · Expires ${row.expiry_date}` : ""}
                      {` · Receipt ${row.receipt_code}`}
                      {` · Received at Farm ${row.received_at_farm_id.slice(0, 8)}`}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {actions.map((disposition) => (
                      <button
                        key={disposition}
                        type="button"
                        className="rounded-md border border-wl-border-strong bg-wl-surface px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover"
                        onClick={() => {
                          setError(null);
                          setSelection({ cohortId: row.inventory_quantity_cohort_id, kind: "ORDINARY", disposition });
                        }}
                      >
                        {disposition === "RELEASED" ? "Release"
                          : disposition === "HELD" ? "Hold"
                          : disposition === "REJECTED" ? "Reject"
                          : "Hold Release"}
                      </button>
                    ))}
                    {actions.length > 0 && (
                      <button
                        type="button"
                        className="rounded-md border border-wl-border-strong bg-wl-surface px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover"
                        onClick={() => {
                          setError(null);
                          setSelection({ cohortId: row.inventory_quantity_cohort_id, kind: "PARTIAL" });
                        }}
                      >
                        Apply to part of quantity
                      </button>
                    )}
                    {canCorrect && (
                      <button
                        type="button"
                        className="rounded-md border border-wl-border-strong bg-wl-surface px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover"
                        onClick={() => {
                          setError(null);
                          setSelection({ cohortId: row.inventory_quantity_cohort_id, kind: "CORRECT" });
                        }}
                      >
                        Correct decision
                      </button>
                    )}
                    {canCorrect && (
                      <button
                        type="button"
                        className="rounded-md border border-wl-border-strong bg-wl-surface px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover"
                        onClick={() => {
                          setError(null);
                          setSelection({ cohortId: row.inventory_quantity_cohort_id, kind: "PARTIAL_CORRECT" });
                        }}
                      >
                        Correct decision for part of quantity
                      </button>
                    )}
                  </div>
                </div>

                {isRestrictedNow && selection && row.current_event_id && (
                  <div className="mt-3">
                    <QualityActionPanel
                      row={row}
                      kind={selection.kind}
                      disposition={selection.kind === "ORDINARY" ? selection.disposition : undefined}
                      legalReplacements={
                        selection.kind === "PARTIAL" ? actions
                          : selection.kind === "CORRECT" ? ["RELEASED", "HELD", "REJECTED", "HOLD_RELEASED"]
                          : undefined
                      }
                      isSubmitting={
                        dispositionMutation.isPending || partialMutation.isPending || correctMutation.isPending ||
                        partialCorrectMutation.isPending
                      }
                      serverError={error}
                      onCancel={close}
                      onSubmitOrdinary={({ reason, effectiveTime }) => {
                        if (selection.kind !== "ORDINARY") return;
                        setError(null);
                        dispositionMutation.mutate(
                          {
                            client_command_id: crypto.randomUUID(),
                            inventory_quantity_cohort_id: row.inventory_quantity_cohort_id,
                            disposition: selection.disposition,
                            effective_time: effectiveTime,
                            reason: reason.trim() || null,
                          },
                          { onSuccess: close, onError: (err) => setError(asAppError(err)) },
                        );
                      }}
                      onSubmitPartial={({ quantity, disposition, reason, effectiveTime }) => {
                        setError(null);
                        partialMutation.mutate(
                          {
                            client_command_id: crypto.randomUUID(),
                            inventory_quantity_cohort_id: row.inventory_quantity_cohort_id,
                            quantity,
                            disposition,
                            effective_time: effectiveTime,
                            reason: reason.trim() || null,
                          },
                          { onSuccess: close, onError: (err) => setError(asAppError(err)) },
                        );
                      }}
                      onSubmitCorrect={({ reason, replacementDisposition, effectiveTime }) => {
                        setError(null);
                        correctMutation.mutate(
                          {
                            client_command_id: crypto.randomUUID(),
                            inventory_quantity_cohort_id: row.inventory_quantity_cohort_id,
                            target_event_id: row.current_event_id as string,
                            reason,
                            replacement_disposition: replacementDisposition,
                            effective_time: effectiveTime,
                          },
                          { onSuccess: close, onError: (err) => setError(asAppError(err)) },
                        );
                      }}
                      onSubmitPartialCorrect={({ quantity, correctedDisposition, reason, effectiveTime }) => {
                        setError(null);
                        partialCorrectMutation.mutate(
                          {
                            client_command_id: crypto.randomUUID(),
                            inventory_quantity_cohort_id: row.inventory_quantity_cohort_id,
                            target_event_id: row.current_event_id as string,
                            quantity,
                            corrected_disposition: correctedDisposition,
                            reason,
                            effective_time: effectiveTime,
                          },
                          { onSuccess: close, onError: (err) => setError(asAppError(err)) },
                        );
                      }}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
