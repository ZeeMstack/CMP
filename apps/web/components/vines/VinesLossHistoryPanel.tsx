"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { VinesProductionDispositionHistoryRead } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { VINES_DISPOSITION_REASONS } from "@/lib/validation/vinesProductionDisposition";

const errorClass = "text-xs text-red-700";

/** VINES-OPS-002: void-only inline correction -- no mode choice, no
 * corrected-fact fields (unlike Leafy's `CorrectionForm`), since `correct_
 * grow_cube_disposition` currently supports reversal only (see its own
 * service docstring for why replace-mode is deferred). */
function VoidCorrectionConfirm({
  eventId, onSubmit, onCancel, isSubmitting, serverError,
}: {
  eventId: string;
  onSubmit: (eventId: string) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border-subtle bg-surface-subtle p-3 text-sm">
      <p className="text-ink">Void this loss record? The named plant(s) return to living population.</p>
      {serverError && <p className={errorClass}>{friendlyMutationErrorMessage(serverError)}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="button" variant="primary" onClick={() => onSubmit(eventId)} disabled={isSubmitting}>
          {isSubmitting ? "Voiding…" : "Confirm void"}
        </Button>
      </div>
    </div>
  );
}

/** VINES-OPS-002: Vines-side sibling of `PlantLossHistoryPanel` -- one row
 * per Grow Bag population lineage, remains visible after the lineage's own
 * BCA is released (never disappears merely because the Grow Bag's Living
 * reached zero). Each REDUCTION event names its own specific Grow Cube
 * code(s), never a bare count. */
export function VinesLossHistoryPanel({
  lineages,
  canCorrect,
  onCorrect,
  correctingEventId,
  isSubmitting,
  serverError,
}: {
  lineages: VinesProductionDispositionHistoryRead[];
  canCorrect: boolean;
  onCorrect: (eventId: string) => Promise<void>;
  correctingEventId: string | null;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [openEventId, setOpenEventId] = useState<string | null>(null);

  if (lineages.length === 0) {
    return <p className="text-sm text-ink-muted">No plant loss history recorded yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-4">
      {lineages.map((lineage) => (
        <li
          key={lineage.population_root_batch_carrier_assignment_id}
          className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface p-3"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-serif text-sm font-semibold text-ink">
              {lineage.grow_bag_code} — {lineage.batch_code}
              {lineage.gutter_code ? ` · ${lineage.gutter_code}` : ""}
            </span>
            <div className="flex items-center gap-2">
              <StatusBadge label={lineage.is_active ? "Active" : "Released"} tone={lineage.is_active ? "active" : "closed"} />
              <span className="text-xs text-ink-muted">
                Opening {lineage.opening_population.toLocaleString()} · Current{" "}
                {lineage.current_living_population.toLocaleString()}
              </span>
            </div>
          </div>
          <ul className="divide-y divide-border-subtle text-sm">
            {lineage.events.map((event) => (
              <li key={event.id} className="flex flex-col gap-1 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-ink">
                    {event.event_kind === "REDUCTION" ? "Loss" : "Restored"}{" "}
                    {Math.abs(event.quantity_delta).toLocaleString()}
                    {" — "}
                    {VINES_DISPOSITION_REASONS.find((r) => r.code === event.reason_code)?.label ?? event.reason_code}
                  </span>
                  <span className="text-xs text-ink-muted">{new Date(event.effective_time).toLocaleString()}</span>
                </div>
                {event.grow_cubes.length > 0 && (
                  <p className="text-xs text-ink-muted">Plant(s): {event.grow_cubes.map((c) => c.code).join(", ")}</p>
                )}
                {event.note && <p className="text-xs text-ink-muted">{event.note}</p>}
                {event.is_reversed && <p className="text-xs text-ink-muted">Corrected — see reversal below</p>}
                {canCorrect && event.event_kind === "REDUCTION" && !event.is_reversed && (
                  <div>
                    {openEventId === event.id ? (
                      <VoidCorrectionConfirm
                        eventId={event.id}
                        onSubmit={(eventId) => onCorrect(eventId)}
                        onCancel={() => setOpenEventId(null)}
                        isSubmitting={isSubmitting && correctingEventId === event.id}
                        serverError={correctingEventId === event.id ? serverError : null}
                      />
                    ) : (
                      <Button type="button" variant="secondary" onClick={() => setOpenEventId(event.id)}>
                        Correct
                      </Button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
