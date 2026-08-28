"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { RecordProductionDispositionCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  DEFAULT_RECORD_PLANT_LOSS_FORM_VALUES,
  PRODUCTION_DISPOSITION_REASONS,
  recordPlantLossFormSchema,
  type RecordPlantLossFormValues,
} from "@/lib/validation/productionDisposition";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

/** LEAFY-OPS-001: "Record Plant Loss" -- the operator-facing action name is
 * frozen (never "mortality" in UI text). Low-typing, inline flow matching
 * greenhouse-floor use: configure -> review -> confirm, mirroring
 * `ProductionTransferForm.tsx`'s established shape but scaled down for a
 * single-Plate, single-count command. Backend remains authoritative on
 * over-loss; this client-side check is advisory only (superRefine in the
 * schema), matching every other frozen NURSERY-OPS-005B UI precedent. */
export function RecordPlantLossForm({
  plateCode,
  batchCarrierAssignmentId,
  currentLivingPopulation,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  plateCode: string;
  batchCarrierAssignmentId: string;
  currentLivingPopulation: number;
  onSubmit: (payload: RecordProductionDispositionCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const initial = nowDateAndTime();

  const {
    register, handleSubmit, watch, getValues, formState: { errors },
  } = useForm<RecordPlantLossFormValues>({
    resolver: zodResolver(recordPlantLossFormSchema),
    defaultValues: {
      ...DEFAULT_RECORD_PLANT_LOSS_FORM_VALUES,
      batch_carrier_assignment_id: batchCarrierAssignmentId,
      plate_code: plateCode,
      current_living_population: currentLivingPopulation,
      effective_date: initial.date,
      effective_time_of_day: initial.time,
    },
    mode: "onBlur",
  });

  // Mirrors ProductionTransferForm.tsx's own established 409 handling: a
  // conflict means the population this draft was reviewed against has
  // changed elsewhere (e.g. a concurrent disposition). Forces back to
  // Configure to see and re-review the refreshed authoritative population
  // (the parent keeps `currentLivingPopulation` live from the invalidated
  // query) -- never straight back to a stale Review, never an automatic
  // resubmit. The entered count/reason/note draft itself is untouched
  // (react-hook-form state persists across the step change).
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  const reasonCode = watch("reason_code");
  const plantLossCount = watch("plant_loss_count");
  const resultingPopulation = currentLivingPopulation - (Number.isFinite(plantLossCount) ? plantLossCount : 0);

  function goToReview(values: RecordPlantLossFormValues) {
    void values;
    setStep("review");
  }

  function confirm() {
    const values = getValues();
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const fingerprint = JSON.stringify({
      batch_carrier_assignment_id: values.batch_carrier_assignment_id,
      plant_loss_count: values.plant_loss_count,
      reason_code: values.reason_code,
      effective_time: effectiveTime,
      note: values.note.trim() || null,
    });
    // Same id + unchanged payload -> exact replay; any edit since the last
    // submission rotates the id, mirroring ProductionTransferForm.tsx's own
    // established idempotency-lifecycle pattern.
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: RecordProductionDispositionCreate = {
      client_command_id: idToUse,
      batch_carrier_assignment_id: values.batch_carrier_assignment_id,
      plant_loss_count: values.plant_loss_count,
      reason_code: values.reason_code,
      effective_time: effectiveTime,
      note: values.note.trim() || null,
    };
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <h2 className="font-serif text-base font-semibold text-ink">Review before recording</h2>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div>
            <dt className="text-ink-muted">Plate</dt>
            <dd className="font-medium text-ink">{values.plate_code}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Current living</dt>
            <dd className="font-medium text-ink">{currentLivingPopulation.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Plant loss</dt>
            <dd className="font-medium text-ink">{values.plant_loss_count.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Resulting living</dt>
            <dd className="font-medium text-ink">{resultingPopulation.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Reason</dt>
            <dd className="font-medium text-ink">
              {PRODUCTION_DISPOSITION_REASONS.find((r) => r.code === values.reason_code)?.label ?? values.reason_code}
            </dd>
          </div>
          <div>
            <dt className="text-ink-muted">Occurred at</dt>
            <dd className="font-medium text-ink">
              {values.effective_date} {values.effective_time_of_day}
            </dd>
          </div>
        </dl>
        {values.note && (
          <p className="text-sm text-ink-muted">
            Note: <span className="text-ink">{values.note}</span>
          </p>
        )}
        {resultingPopulation === 0 && (
          <p className="text-sm text-ink-muted">
            Current Living will become 0 and the biological assignment will release. The physical Plate remains at
            its current location.
          </p>
        )}
        {serverError && (
          <p role="alert" className={errorClass}>
            {friendlyMutationErrorMessage(serverError)}
          </p>
        )}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={confirm} disabled={isSubmitting}>
            {isSubmitting ? "Recording…" : "Confirm"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit(goToReview)} className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-base font-semibold text-ink">Record Plant Loss — {plateCode}</h2>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      <dl className="text-sm">
        <div>
          <dt className="text-ink-muted">Current living</dt>
          <dd className="font-medium text-ink">{currentLivingPopulation.toLocaleString()}</dd>
        </div>
      </dl>

      <Field label="Plant loss count" error={errors.plant_loss_count?.message}>
        <input
          type="number" min={1} step={1} className={inputClass}
          {...register("plant_loss_count", { valueAsNumber: true })}
        />
      </Field>
      {Number.isFinite(plantLossCount) && plantLossCount > 0 && (
        <p className="text-xs text-ink-muted">Resulting living: {resultingPopulation.toLocaleString()}</p>
      )}

      <Field label="Reason" error={errors.reason_code?.message}>
        <select className={inputClass} {...register("reason_code")}>
          <option value="">Select a reason…</option>
          {PRODUCTION_DISPOSITION_REASONS.map((r) => (
            <option key={r.code} value={r.code}>
              {r.label}
            </option>
          ))}
        </select>
      </Field>

      <Field label={`Note ${reasonCode === "other" ? "(required)" : "(optional)"}`} error={errors.note?.message}>
        <textarea className={`${inputClass} min-h-20`} rows={2} {...register("note")} />
      </Field>

      <fieldset className="grid grid-cols-2 gap-3">
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" className={inputClass} {...register("effective_date")} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" className={inputClass} {...register("effective_time_of_day")} />
        </Field>
      </fieldset>

      {serverError && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(serverError)}
        </p>
      )}

      <div>
        <Button type="submit" variant="primary">
          Review
        </Button>
      </div>
    </form>
  );
}
