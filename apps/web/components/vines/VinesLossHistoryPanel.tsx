"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { CorrectVinesGrowCubeDispositionCreate, VinesProductionDispositionHistoryRead } from "@/lib/api/client";
import {
  UNCERTAIN_OUTCOME_COPY,
  toCommandError,
  useFrozenSubmission,
  useReportCommandLocked,
} from "@/lib/commands/frozenSubmission";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { VINES_DISPOSITION_REASONS } from "@/lib/validation/vinesProductionDisposition";

const errorClass = "text-xs text-danger-700";

/** VINES-OPS-002: void-only inline correction -- no mode choice, no
 * corrected-fact fields (unlike Leafy's `CorrectionForm`), since `correct_
 * grow_cube_disposition` currently supports reversal only (see its own
 * service docstring for why replace-mode is deferred). */
function VoidCorrectionConfirm({
  eventId, onSubmit, onCancel, isSubmitting, serverError, onCommandLockedChange,
}: {
  eventId: string;
  onSubmit: (eventId: string, payload: CorrectVinesGrowCubeDispositionCreate) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
  onCommandLockedChange?: (locked: boolean) => void;
}) {
  // UX-OPS-001C/R1: one frozen void attempt per event. An uncertain outcome
  // keeps the same `client_command_id` for Retry and disables Cancel -- no
  // read here can prove whether the void applied, so it is never abandoned.
  const command = useFrozenSubmission<CorrectVinesGrowCubeDispositionCreate & Record<string, unknown>>();
  useReportCommandLocked(command.outcome, onCommandLockedChange);
  const busy = isSubmitting || command.outcome === "submitting";

  function send(payload: CorrectVinesGrowCubeDispositionCreate) {
    onSubmit(eventId, payload).then(
      () => command.handleSuccess(),
      (error) => command.handleError(toCommandError(error)),
    );
  }

  function confirm() {
    if (command.outcome === "uncertain") {
      const frozen = command.retry();
      if (frozen) send(frozen);
      return;
    }
    send(command.submit((clientCommandId) => ({ client_command_id: clientCommandId })));
  }

  const error = serverError ?? command.error;
  return (
    <div className="flex flex-col gap-2 rounded-md border border-wl-border bg-wl-surface-sunken p-3 text-sm">
      <p className="text-wl-text">Void this loss record? The named plant(s) return to living population.</p>
      {error && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(error)}
          {command.outcome === "uncertain" && ` ${UNCERTAIN_OUTCOME_COPY}`}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy || command.outcome !== "editing"}>
          Cancel
        </Button>
        <Button type="button" variant="primary" onClick={confirm} disabled={busy}>
          {busy ? "Voiding…" : command.outcome === "uncertain" ? "Retry void" : "Confirm void"}
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
  onCommandLockedChange,
}: {
  lineages: VinesProductionDispositionHistoryRead[];
  canCorrect: boolean;
  onCorrect: (eventId: string, payload: CorrectVinesGrowCubeDispositionCreate) => Promise<void>;
  correctingEventId: string | null;
  isSubmitting: boolean;
  serverError?: AppError | null;
  onCommandLockedChange?: (locked: boolean) => void;
}) {
  const [openEventId, setOpenEventId] = useState<string | null>(null);

  if (lineages.length === 0) {
    return <p className="text-sm text-wl-text-secondary">No plant loss history recorded yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-4">
      {lineages.map((lineage) => (
        <li
          key={lineage.population_root_batch_carrier_assignment_id}
          className="flex flex-col gap-2 rounded-xl border border-wl-border bg-wl-surface-raised p-3"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-serif text-sm font-semibold text-wl-text">
              {lineage.grow_bag_code} — {lineage.batch_code}
              {lineage.gutter_code ? ` · ${lineage.gutter_code}` : ""}
            </span>
            <div className="flex items-center gap-2">
              <StatusBadge label={lineage.is_active ? "Active" : "Released"} tone={lineage.is_active ? "active" : "closed"} />
              <span className="text-xs text-wl-text-secondary">
                Opening {lineage.opening_population.toLocaleString()} · Current{" "}
                {lineage.current_living_population.toLocaleString()}
              </span>
            </div>
          </div>
          <ul className="divide-y divide-wl-border text-sm">
            {lineage.events.map((event) => (
              <li key={event.id} className="flex flex-col gap-1 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-wl-text">
                    {event.event_kind === "REDUCTION" ? "Loss" : "Restored"}{" "}
                    {Math.abs(event.quantity_delta).toLocaleString()}
                    {" — "}
                    {VINES_DISPOSITION_REASONS.find((r) => r.code === event.reason_code)?.label ?? event.reason_code}
                  </span>
                  <span className="text-xs text-wl-text-secondary">{new Date(event.effective_time).toLocaleString()}</span>
                </div>
                {event.grow_cubes.length > 0 && (
                  <p className="text-xs text-wl-text-secondary">Plant(s): {event.grow_cubes.map((c) => c.code).join(", ")}</p>
                )}
                {event.note && <p className="text-xs text-wl-text-secondary">{event.note}</p>}
                {event.is_reversed && <p className="text-xs text-wl-text-secondary">Corrected — see reversal below</p>}
                {canCorrect && event.event_kind === "REDUCTION" && !event.is_reversed && (
                  <div>
                    {openEventId === event.id ? (
                      <VoidCorrectionConfirm
                        eventId={event.id}
                        onSubmit={(eventId, payload) => onCorrect(eventId, payload)}
                        onCancel={() => setOpenEventId(null)}
                        isSubmitting={isSubmitting && correctingEventId === event.id}
                        // The page clears `correctingEventId` once the attempt settles,
                        // so the open confirm (not the in-flight id) owns the error.
                        serverError={openEventId === event.id ? serverError : null}
                        onCommandLockedChange={onCommandLockedChange}
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
