"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { CorrectProductionDispositionCreate, ProductionDispositionHistoryRead } from "@/lib/api/client";
import {
  UNCERTAIN_OUTCOME_COPY,
  toCommandError,
  useFrozenSubmission,
  useReportCommandLocked,
} from "@/lib/commands/frozenSubmission";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { PRODUCTION_DISPOSITION_REASONS, type CorrectPlantLossFormValues } from "@/lib/validation/productionDisposition";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const errorClass = "text-xs text-danger-700";

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

/** Inline correction form for one REDUCTION event -- pure reversal (void) or
 * reversal + replacement, shown only to callers who already hold
 * `canCorrect` (BIOLOGICAL_DISPOSITION_CORRECT). Never hides or rewrites the
 * original event -- it stays visible in the same history list once this
 * closes. */
function CorrectionForm({
  eventId,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
  onCommandLockedChange,
}: {
  eventId: string;
  onSubmit: (eventId: string, payload: CorrectProductionDispositionCreate) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
  onCommandLockedChange?: (locked: boolean) => void;
}) {
  const initial = nowDateAndTime();
  const [values, setValues] = useState<CorrectPlantLossFormValues>({
    mode: "void", plant_loss_count: undefined, reason_code: "", note: "",
    effective_date: initial.date, effective_time_of_day: initial.time,
  });
  const [validationError, setValidationError] = useState<string | null>(null);
  // UX-OPS-001C/R1: one frozen attempt per actual submission of THIS event's
  // correction (each event gets its own form instance). Uncertain -> the
  // byte-identical payload is kept for Retry and Cancel/fields are locked;
  // definitive rejection or success releases it.
  const command = useFrozenSubmission<CorrectProductionDispositionCreate & Record<string, unknown>>();
  useReportCommandLocked(command.outcome, onCommandLockedChange);
  const locked = command.outcome !== "editing";
  const busy = isSubmitting || command.outcome === "submitting";

  function send(payload: CorrectProductionDispositionCreate) {
    onSubmit(eventId, payload).then(
      () => {
        command.handleSuccess();
        onCancel(); // success -- close the form; the original event and its
        // correction now both appear in the same history list once refetched.
      },
      (error) => command.handleError(toCommandError(error)),
    );
  }

  function submit() {
    if (command.outcome === "uncertain") {
      const frozen = command.retry();
      if (frozen) send(frozen);
      return;
    }
    if (values.mode === "replace") {
      if (!values.plant_loss_count || values.plant_loss_count <= 0) {
        setValidationError("Corrected loss count is required");
        return;
      }
      if (!values.reason_code) {
        setValidationError("Reason is required");
        return;
      }
      if (values.reason_code === "other" && !(values.note ?? "").trim()) {
        setValidationError("A note is required when reason is Other");
        return;
      }
    }
    setValidationError(null);
    const corrected =
      values.mode === "void"
        ? null
        : {
            plant_loss_count: values.plant_loss_count as number,
            reason_code: values.reason_code as string,
            effective_time: new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString(),
            note: (values.note ?? "").trim() || null,
          };
    send(command.submit((clientCommandId) => ({ client_command_id: clientCommandId, corrected })));
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border border-wl-border bg-wl-surface-sunken p-3">
      <fieldset disabled={locked} className="flex min-w-0 flex-col gap-3">
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="radio" name={`mode-${eventId}`} checked={values.mode === "void"}
            onChange={() => setValues((v) => ({ ...v, mode: "void" }))}
          />
          Pure reversal (void)
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio" name={`mode-${eventId}`} checked={values.mode === "replace"}
            onChange={() => setValues((v) => ({ ...v, mode: "replace" }))}
          />
          Replace with corrected loss
        </label>
      </div>
      {values.mode === "replace" && (
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span>Corrected loss count</span>
            <input
              type="number" min={1} step={1} className={inputClass}
              value={values.plant_loss_count ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, plant_loss_count: Number(e.target.value) }))}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span>Reason</span>
            <select
              className={inputClass} value={values.reason_code}
              onChange={(e) => setValues((v) => ({ ...v, reason_code: e.target.value }))}
            >
              <option value="">Select a reason…</option>
              {PRODUCTION_DISPOSITION_REASONS.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-2 flex flex-col gap-1 text-sm">
            <span>Note {values.reason_code === "other" ? "(required)" : "(optional)"}</span>
            <input
              className={inputClass} value={values.note ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, note: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span>Date</span>
            <input
              type="date" className={inputClass} value={values.effective_date}
              onChange={(e) => setValues((v) => ({ ...v, effective_date: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span>Time</span>
            <input
              type="time" className={inputClass} value={values.effective_time_of_day}
              onChange={(e) => setValues((v) => ({ ...v, effective_time_of_day: e.target.value }))}
            />
          </label>
        </div>
      )}
      </fieldset>
      {validationError && <p className={errorClass}>{validationError}</p>}
      {(serverError ?? command.error) && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage((serverError ?? command.error) as AppError)}
          {command.outcome === "uncertain" && ` ${UNCERTAIN_OUTCOME_COPY}`}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy || locked}>
          Cancel
        </Button>
        <Button type="button" variant="primary" onClick={submit} disabled={busy}>
          {busy ? "Submitting…" : command.outcome === "uncertain" ? "Retry correction" : "Submit correction"}
        </Button>
      </div>
    </div>
  );
}

/** LEAFY-OPS-001 section 32/44: Plant Loss History remains usable for a
 * fully-exhausted (released) population lineage -- it never disappears
 * merely because the lineage is no longer in Active Production Plates.
 * `canCorrect` gates the correction action visibility only (the backend is
 * the real authority via BIOLOGICAL_DISPOSITION_CORRECT). */
export function PlantLossHistoryPanel({
  lineages,
  canCorrect,
  onCorrect,
  correctingEventId,
  isSubmitting,
  serverError,
  onCommandLockedChange,
}: {
  lineages: ProductionDispositionHistoryRead[];
  canCorrect: boolean;
  onCorrect: (eventId: string, payload: CorrectProductionDispositionCreate) => Promise<void>;
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
              {lineage.plate_code} — {lineage.batch_code}
            </span>
            <div className="flex items-center gap-2">
              <StatusBadge label={lineage.is_active ? "Active" : "Released"} tone={lineage.is_active ? "active" : "closed"} />
              {/* Current is the authoritative living population; Opening is
                  historical/reconciliation context only -- both stay in one
                  plain-text readout since they're read together, but Current
                  is never merged into or replaced by Opening. */}
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
                    {/* BROWSER QA CORRECTION 2: `plant_loss_quantity` is a
                     * REDUCTION-only field (deliberately 0 for a REVERSAL,
                     * which restores rather than loses plants) -- the
                     * magnitude shown here must always come from the
                     * signed `quantity_delta` itself, never that field, or
                     * a REVERSAL renders as a misleading "Reversal 0". */}
                    {event.event_kind === "REDUCTION" ? "Loss" : "Restored"}{" "}
                    {Math.abs(event.quantity_delta).toLocaleString()}
                    {" — "}
                    {PRODUCTION_DISPOSITION_REASONS.find((r) => r.code === event.reason_code)?.label ?? event.reason_code}
                  </span>
                  <span className="text-xs text-wl-text-secondary">{new Date(event.effective_time).toLocaleString()}</span>
                </div>
                {event.note && <p className="text-xs text-wl-text-secondary">{event.note}</p>}
                {event.is_reversed && <p className="text-xs text-wl-text-secondary">Corrected — see reversal below</p>}
                {canCorrect && event.event_kind === "REDUCTION" && !event.is_reversed && (
                  <div>
                    {openEventId === event.id ? (
                      <CorrectionForm
                        eventId={event.id}
                        onSubmit={(eventId, payload) => onCorrect(eventId, payload)}
                        onCancel={() => setOpenEventId(null)}
                        isSubmitting={isSubmitting && correctingEventId === event.id}
                        serverError={correctingEventId === event.id ? serverError : null}
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
