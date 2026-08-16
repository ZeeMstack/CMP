"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import type { CorrectSeedlingDispositionCreate, SeedlingDispositionEventRead } from "@/lib/api/client";
import { useSeedlingDispositionReasons } from "@/lib/query/hooks";
import {
  DEFAULT_CORRECT_DISPOSITION_FORM_VALUES,
  buildCorrectDispositionPayload,
  correctDispositionFormSchema,
  type CorrectDispositionFormValues,
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

/** NURSERY-OPS-003B: correcting a disposition is one atomic backend command
 * either way (section 0.A) -- Void creates only the exact reversal of the
 * target; Replace creates that same reversal plus one new, corrected
 * REDUCTION (section 0.B). The original erroneous event is never hidden or
 * rewritten -- it stays visible in history alongside the correction. One
 * form, one confirmation, one submit. */
export function CorrectDispositionForm({
  farmId, target, onSubmit, onCancel, isSubmitting, serverError,
}: {
  farmId: string;
  target: SeedlingDispositionEventRead;
  onSubmit: (payload: CorrectSeedlingDispositionCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const initial = nowDateAndTime();
  const {
    register, watch, handleSubmit, formState: { errors },
  } = useForm<CorrectDispositionFormValues>({
    resolver: zodResolver(correctDispositionFormSchema),
    defaultValues: {
      ...DEFAULT_CORRECT_DISPOSITION_FORM_VALUES,
      quantity: String(Math.abs(target.quantity_delta)),
      reason_code: target.reason_code,
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      note: target.note ?? "",
    },
    mode: "onBlur",
  });
  const reasonsQuery = useSeedlingDispositionReasons(farmId);
  const reasons = reasonsQuery.data ?? [];
  const mode = watch("mode");
  const watchedReason = watch("reason_code");

  function submit(values: CorrectDispositionFormValues) {
    onSubmit(buildCorrectDispositionPayload(values, clientCommandId));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Correct this entry</h3>
        <p className="text-sm text-ink-muted">
          Originally recorded {Math.abs(target.quantity_delta)} — {target.reason_code} on{" "}
          {new Date(target.effective_time).toLocaleString()}.
        </p>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="px-1 text-sm font-semibold text-ink">What happened</legend>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="radio" value="void" {...register("mode")} className="h-4 w-4" />
          This entry should never have been recorded (void it)
        </label>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="radio" value="replace" {...register("mode")} className="h-4 w-4" />
          This entry was recorded incorrectly (replace it with the correct facts)
        </label>
      </fieldset>

      {mode === "replace" && (
        <>
          <fieldset className="grid grid-cols-1 gap-4 rounded-lg border border-border-subtle p-4 sm:grid-cols-2">
            <legend className="px-1 text-sm font-semibold text-ink">Corrected facts</legend>
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

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={onCancel}
          disabled={isSubmitting}
          className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
        >
          {isSubmitting ? "Saving…" : mode === "void" ? "Confirm void" : "Confirm correction"}
        </button>
      </div>
    </form>
  );
}
