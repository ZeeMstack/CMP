"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { useCurrentGerminationOutcomes, useGerminationTrays, useRecordGerminationOutcomes } from "@/lib/query/hooks";
import {
  DEFAULT_GERMINATION_OUTCOME_FORM_VALUES,
  buildGerminationOutcomePayload,
  germinationOutcomeFormSchema,
  livingSeedlingCount,
  type GerminationOutcomeFormValues,
} from "@/lib/validation/germinationOutcome";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-sm font-medium text-wl-text";
const errorClass = "text-xs text-danger-700";

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

const PLACEMENT_LABEL: Record<string, string> = {
  awaiting_placement: "Awaiting placement",
  elsewhere: "Elsewhere",
  in_germination: "In Germination",
  unknown: "Unknown",
};

/** NURSERY-OPS-002B: records the modern, INDIVIDUAL-SEEDLING-based
 * Germination outcome for one Tray -- distinct from the legacy site-based
 * GerminationCheck, which this form never shows. Physical placement is
 * informational context only, never a hard requirement (a Tray that has
 * already moved on can still receive a late/historical entry). This
 * form owns its own mutation (unlike PlaceTrolleyForm/MoveTrayForm) because
 * its command URL is scoped to whichever Batch the operator's Tray
 * selection resolves to -- not known until a Tray is picked. */
export interface RecordOutcomeSuccessInfo {
  assignmentId: string;
  batchCode: string;
  trayCode: string;
  normalCount: number;
  abnormalCount: number;
  assessmentComplete: boolean;
}

export function RecordOutcomeForm({
  farmId, onSuccess, onCancel, initialAssignmentId,
}: {
  farmId: string;
  onSuccess: (info: RecordOutcomeSuccessInfo) => void;
  onCancel: () => void;
  // PILOT-UX-002B: opened from a worklist row, the assignment is already
  // known -- frozen here (never re-derived from a refetch) so the operator
  // is never asked to find/select the same Tray again, and a background
  // query refresh can never silently retarget the open form (section 8/14).
  initialAssignmentId?: string;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [selectedAssignmentId, setSelectedAssignmentId] = useState(initialAssignmentId ?? "");
  const [serverError, setServerError] = useState<string | null>(null);

  const initial = nowDateAndTime();
  const {
    register, trigger, getValues, watch, formState: { errors },
  } = useForm<GerminationOutcomeFormValues>({
    resolver: zodResolver(germinationOutcomeFormSchema),
    defaultValues: { ...DEFAULT_GERMINATION_OUTCOME_FORM_VALUES, effective_date: initial.date, effective_time_of_day: initial.time },
    mode: "onBlur",
  });

  const traysQuery = useGerminationTrays(farmId);
  const trays = traysQuery.data ?? [];
  const selectedTray = trays.find((t) => t.batch_carrier_assignment_id === selectedAssignmentId);
  const currentQuery = useCurrentGerminationOutcomes(farmId, selectedTray?.batch_id ?? "");
  const trayContext = currentQuery.data?.trays.find((t) => t.batch_carrier_assignment_id === selectedAssignmentId);
  const mutation = useRecordGerminationOutcomes(farmId, selectedTray?.batch_id ?? "");

  const watched = watch();
  const living = livingSeedlingCount(watched);
  const gap = selectedTray ? selectedTray.seeds_sown - living : null;

  async function goToReview() {
    if (!selectedAssignmentId) return;
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    if (!selectedTray) return;
    setServerError(null);
    const values = getValues();
    const payload = buildGerminationOutcomePayload(values, clientCommandId, selectedAssignmentId);
    mutation.mutate(payload, {
      onSuccess: () =>
        onSuccess({
          assignmentId: selectedAssignmentId,
          batchCode: selectedTray.batch_code,
          trayCode: selectedTray.tray.code,
          normalCount: values.normal_seedling_count,
          abnormalCount: values.abnormal_seedling_count,
          assessmentComplete: values.assessment_complete,
        }),
      onError: (error) => setServerError(error instanceof AppError ? error.message : "Something went wrong. Please try again."),
    });
  }

  if (initialAssignmentId && traysQuery.isSuccess && !selectedTray) {
    return (
      <div className="flex flex-col gap-4">
        <p className="rounded-md border border-wl-border-strong bg-wl-flag-bg px-3 py-2 text-sm text-wl-flag-fg">
          This Seed Tray&apos;s data could not be found -- it may have moved since the worklist last loaded. Return
          to the worklist to see its current status.
        </p>
        <Button type="button" variant="secondary" className="self-start" onClick={onCancel}>
          Back to worklist
        </Button>
      </div>
    );
  }

  if (step === "review" && selectedTray) {
    const values = getValues();
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <h2 className="font-serif text-base font-semibold text-wl-text">
            {values.assessment_complete ? "Review before completing" : "Review provisional observation"}
          </h2>
          {!values.assessment_complete && (
            <p className="text-sm text-wl-text-secondary">
              Provisional observation. The seed-to-living gap shown below is not a final categorized loss.
            </p>
          )}
          {values.assessment_complete && (
            <p className="text-sm text-wl-text-secondary">
              This will establish the current Germination handoff quantity for this Tray.
            </p>
          )}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-wl-text-secondary">Batch</dt>
              <dd className="font-medium text-wl-text">{selectedTray.batch_code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seed Tray</dt>
              <dd className="font-medium text-wl-text">{selectedTray.tray.code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seeds sown</dt>
              <dd className="font-medium text-wl-text">{selectedTray.seeds_sown.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Normal seedlings</dt>
              <dd className="font-medium text-wl-text">{values.normal_seedling_count}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Abnormal seedlings</dt>
              <dd className="font-medium text-wl-text">{values.abnormal_seedling_count}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Living total</dt>
              <dd className="font-medium text-wl-text">{living.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seeds not represented by living seedlings</dt>
              <dd className="font-medium text-wl-text">{gap?.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Occurred at</dt>
              <dd className="font-medium text-wl-text">
                {values.effective_date} {values.effective_time_of_day}
              </dd>
            </div>
          </dl>
        </div>
        {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={mutation.isPending}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={submitReview} disabled={mutation.isPending}>
            {mutation.isPending ? "Recording…" : values.assessment_complete ? "Complete Outcome" : "Save Observation"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        goToReview();
      }}
      className="flex flex-col gap-6"
    >
      {initialAssignmentId && selectedTray && (
        <p className="rounded-md border border-wl-border-strong bg-wl-brand-subtle px-3 py-2 text-xs text-wl-brand">
          From the Germination worklist — Batch {selectedTray.batch_code}, Seed Tray {selectedTray.tray.code}.
        </p>
      )}
      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Seed Tray</legend>
        {initialAssignmentId && selectedTray ? (
          <p className="text-sm font-medium text-wl-text">
            {selectedTray.batch_code} — {selectedTray.tray.code}
          </p>
        ) : traysQuery.isSuccess && trays.length === 0 ? (
          <p className="text-sm text-wl-text-secondary">No Sown Seed Trays are eligible for a Germination outcome yet.</p>
        ) : (
          <Field label="Seed Tray">
            <select
              value={selectedAssignmentId}
              onChange={(e) => setSelectedAssignmentId(e.target.value)}
              className={inputClass}
            >
              <option value="">Select a Seed Tray…</option>
              {trays.map((t) => (
                <option key={t.batch_carrier_assignment_id} value={t.batch_carrier_assignment_id}>
                  {t.batch_code} — {t.tray.code} ({PLACEMENT_LABEL[t.state] ?? t.state})
                </option>
              ))}
            </select>
          </Field>
        )}
        {selectedTray && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-wl-text-secondary">Crop / Variety</dt>
              <dd className="font-medium text-wl-text">
                {selectedTray.seed_lot.crop.common_name} / {selectedTray.seed_lot.variety.name}
              </dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seed Lot</dt>
              <dd className="font-medium text-wl-text">{selectedTray.seed_lot.code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seeds sown</dt>
              <dd className="font-medium text-wl-text">{selectedTray.seeds_sown.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Sown Sites</dt>
              <dd className="font-medium text-wl-text">{trayContext?.sown_site_count ?? "Not recorded"}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Current placement</dt>
              <dd className="font-medium text-wl-text">{PLACEMENT_LABEL[selectedTray.state] ?? selectedTray.state}</dd>
            </div>
            {trayContext?.latest_snapshot && (
              <div>
                <dt className="text-wl-text-secondary">Previous observation</dt>
                <dd className="font-medium text-wl-text">
                  {trayContext.latest_snapshot.living_seedling_count.toLocaleString()} living (
                  {trayContext.latest_snapshot.assessment_complete ? "completed" : "provisional"})
                </dd>
              </div>
            )}
            {trayContext?.latest_completed_snapshot && (
              <div>
                <dt className="text-wl-text-secondary">Previous handoff</dt>
                <dd className="font-medium text-wl-text">
                  {trayContext.latest_completed_snapshot.living_seedling_count.toLocaleString()} living
                </dd>
              </div>
            )}
          </dl>
        )}
      </fieldset>

      {selectedTray && (
        <>
          <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
            <legend className="px-1 text-sm font-semibold text-wl-text">Seedling counts</legend>
            <p className="text-xs text-wl-text-secondary sm:col-span-2">
              Normal and Abnormal seedlings are both living, emerged seedlings — record the actual counts observed,
              not a loss assessment.
            </p>
            <Field label="Normal seedlings" error={errors.normal_seedling_count?.message}>
              <input
                type="number" min={0}
                {...register("normal_seedling_count", { valueAsNumber: true })}
                className={inputClass}
              />
            </Field>
            <Field label="Abnormal seedlings" error={errors.abnormal_seedling_count?.message}>
              <input
                type="number" min={0}
                {...register("abnormal_seedling_count", { valueAsNumber: true })}
                className={inputClass}
              />
            </Field>
            <p className="rounded-md bg-wl-brand-subtle px-3 py-2 text-sm text-wl-brand sm:col-span-2">
              Normal + Abnormal = <span className="font-semibold">{living.toLocaleString()} living</span> seedlings.
              Living seedlings: {living.toLocaleString()} · Seeds not represented by living seedlings:{" "}
              {gap?.toLocaleString()}
            </p>
          </fieldset>

          <fieldset className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
            <legend className="px-1 text-sm font-semibold text-wl-text">Assessment status</legend>
            <label className="flex items-center gap-2 text-sm text-wl-text">
              <input type="checkbox" {...register("assessment_complete")} className="h-5 w-5" />
              Assessment complete — establish this as the current Germination handoff quantity
            </label>
            {!watched.assessment_complete && (
              <p className="text-xs text-wl-text-secondary">Provisional observation — additional emergence/change is still expected.</p>
            )}
          </fieldset>

          <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
            <legend className="px-1 text-sm font-semibold text-wl-text">Observed date/time</legend>
            <Field label="Date" error={errors.effective_date?.message}>
              <input type="date" {...register("effective_date")} className={inputClass} />
            </Field>
            <Field label="Time" error={errors.effective_time_of_day?.message}>
              <input type="time" {...register("effective_time_of_day")} className={inputClass} />
            </Field>
          </fieldset>

          <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
            <legend className="px-1 text-sm font-semibold text-wl-text">Note (optional)</legend>
            <textarea {...register("note")} className={`${inputClass} min-h-20`} rows={2} />
          </fieldset>
        </>
      )}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!selectedTray}>
          Review
        </Button>
      </div>
    </form>
  );
}
