"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import type { RecordSeedlingDispositionCreate } from "@/lib/api/client";
import { useSeedlingBiologicalTrays, useSeedlingDispositionReasons } from "@/lib/query/hooks";
import {
  DEFAULT_RECORD_DISPOSITION_FORM_VALUES,
  buildRecordDispositionPayload,
  recordDispositionFormSchema,
  type RecordDispositionFormValues,
} from "@/lib/validation/seedlingDisposition";

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

/** NURSERY-OPS-003B: records the positive count of seedlings that stopped
 * continuing in one Seed Tray (section 0.2 -- never a recount of the whole
 * remaining population). Only Trays with an active assignment and a
 * non-zero current balance are offered here (a released or depleted Tray
 * cannot receive a new disposition -- section 1.E). The review step shows
 * the Tray's already-known current balance for context only; the resulting
 * balance is never computed client-side -- the backend always recomputes
 * and returns it authoritatively (section 63). */
export function RecordDispositionForm({
  farmId, preselectedAssignmentId, onSubmit, onCancel, isSubmitting, serverError,
}: {
  farmId: string;
  preselectedAssignmentId?: string;
  onSubmit: (payload: RecordSeedlingDispositionCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [selectedAssignmentId, setSelectedAssignmentId] = useState(preselectedAssignmentId ?? "");

  const initial = nowDateAndTime();
  const {
    register, setValue, trigger, getValues, watch, formState: { errors },
  } = useForm<RecordDispositionFormValues>({
    resolver: zodResolver(recordDispositionFormSchema),
    defaultValues: {
      ...DEFAULT_RECORD_DISPOSITION_FORM_VALUES,
      batch_carrier_assignment_id: preselectedAssignmentId ?? "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
    },
    mode: "onBlur",
  });

  const traysQuery = useSeedlingBiologicalTrays(farmId);
  const eligibleTrays = (traysQuery.data ?? []).filter((t) => t.assignment_active && !t.is_depleted);
  const reasonsQuery = useSeedlingDispositionReasons(farmId);
  const reasons = reasonsQuery.data ?? [];

  const selectedTray = eligibleTrays.find((t) => t.batch_carrier_assignment_id === selectedAssignmentId);
  const watchedReason = watch("reason_code");

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    onSubmit(buildRecordDispositionPayload(getValues(), clientCommandId));
  }

  if (step === "review") {
    const values = getValues();
    const tray = eligibleTrays.find((t) => t.batch_carrier_assignment_id === values.batch_carrier_assignment_id);
    const reason = reasons.find((r) => r.code === values.reason_code);
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4">
          <h2 className="text-sm font-semibold text-ink">Review before recording</h2>
          <p className="text-sm text-ink-muted">
            This will record {values.quantity} seedling(s) as no longer continuing on this Tray. The system will
            confirm the resulting living count after you submit.
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{tray?.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Seed Tray</dt>
              <dd className="font-medium text-ink">{tray?.tray_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Current living seedlings</dt>
              <dd className="font-medium text-ink">{tray?.current_living_seedling_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Quantity</dt>
              <dd className="font-medium text-ink">{values.quantity}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Reason</dt>
              <dd className="font-medium text-ink">{reason?.name ?? values.reason_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Occurred at</dt>
              <dd className="font-medium text-ink">
                {values.effective_date} {values.effective_time_of_day}
              </dd>
            </div>
            {values.note && (
              <div className="sm:col-span-3">
                <dt className="text-ink-muted">Note</dt>
                <dd className="font-medium text-ink">{values.note}</dd>
              </div>
            )}
          </dl>
        </div>
        {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => setStep("configure")}
            disabled={isSubmitting}
            className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Back
          </button>
          <button
            type="button"
            onClick={submitReview}
            disabled={isSubmitting}
            className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
          >
            {isSubmitting ? "Recording…" : "Record disposition"}
          </button>
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
      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Seed Tray</legend>
        {traysQuery.isSuccess && eligibleTrays.length === 0 ? (
          <p className="text-sm text-ink-muted">No Seed Trays are currently eligible for a disposition.</p>
        ) : (
          <Field label="Seed Tray" error={errors.batch_carrier_assignment_id?.message}>
            <select
              {...register("batch_carrier_assignment_id")}
              disabled={Boolean(preselectedAssignmentId)}
              onChange={(e) => {
                setValue("batch_carrier_assignment_id", e.target.value);
                setSelectedAssignmentId(e.target.value);
              }}
              className={inputClass}
            >
              <option value="">Select a Seed Tray…</option>
              {eligibleTrays.map((t) => (
                <option key={t.batch_carrier_assignment_id} value={t.batch_carrier_assignment_id}>
                  {t.batch_code} — {t.tray_code} ({t.current_living_seedling_count.toLocaleString()} living)
                </option>
              ))}
            </select>
          </Field>
        )}
        {selectedTray && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Crop / Variety</dt>
              <dd className="font-medium text-ink">
                {selectedTray.crop_common_name} / {selectedTray.variety_name}
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Starting living seedlings</dt>
              <dd className="font-medium text-ink">{selectedTray.starting_living_seedling_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Current living seedlings</dt>
              <dd className="font-medium text-ink">{selectedTray.current_living_seedling_count.toLocaleString()}</dd>
            </div>
          </dl>
        )}
      </fieldset>

      {selectedTray && (
        <>
          <fieldset className="grid grid-cols-1 gap-4 rounded-lg border border-border-subtle p-4 sm:grid-cols-2">
            <legend className="px-1 text-sm font-semibold text-ink">Seedlings no longer continuing</legend>
            <Field label="Quantity" error={errors.quantity?.message}>
              <input type="number" min={1} step={1} {...register("quantity")} className={inputClass} />
            </Field>
            <Field label="Reason" error={errors.reason_code?.message}>
              <select {...register("reason_code")} className={inputClass}>
                <option value="">Select a reason…</option>
                {reasons.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.name}
                  </option>
                ))}
              </select>
            </Field>
          </fieldset>

          <fieldset className="grid grid-cols-1 gap-4 rounded-lg border border-border-subtle p-4 sm:grid-cols-2">
            <legend className="px-1 text-sm font-semibold text-ink">Occurred date/time</legend>
            <Field label="Date" error={errors.effective_date?.message}>
              <input type="date" {...register("effective_date")} className={inputClass} />
            </Field>
            <Field label="Time" error={errors.effective_time_of_day?.message}>
              <input type="time" {...register("effective_time_of_day")} className={inputClass} />
            </Field>
          </fieldset>

          <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
            <legend className="px-1 text-sm font-semibold text-ink">
              Note {watchedReason === "OTHER" ? "(required for Other)" : "(optional)"}
            </legend>
            <textarea {...register("note")} className={`${inputClass} min-h-20`} rows={2} />
            {errors.note && <span className={errorClass}>{errors.note.message}</span>}
          </fieldset>
        </>
      )}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={!selectedTray}
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
        >
          Review
        </button>
      </div>
    </form>
  );
}
