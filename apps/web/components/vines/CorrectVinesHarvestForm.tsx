"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CorrectVinesHarvestSourceLineCreate, VinesHarvestSourceLineRead } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  correctVinesHarvestFormSchema, HARVEST_CORRECTION_REASONS, type CorrectVinesHarvestFormValues,
} from "@/lib/validation/vinesHarvest";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

const HARVEST_CORRECTION_STALE_MESSAGE =
  "This Harvest line was corrected by someone else. Refresh and review the latest values before trying again.";

function correctionErrorMessage(error: AppError): string {
  if (error.code === "HARVEST_CORRECTION_STALE") return HARVEST_CORRECTION_STALE_MESSAGE;
  if (error.kind === "conflict" && (error.code === "HARVEST_NEGATIVE_LOT_BALANCE" || error.code === "HARVEST_QUALITY_HOLD")) {
    return error.message;
  }
  return friendlyMutationErrorMessage(error);
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

function signed(n: number, unit: string): string {
  const rounded = Math.round(n * 1000) / 1000 || 0;
  const sign = rounded > 0 ? "+" : rounded < 0 ? "-" : "";
  const magnitude = Math.abs(rounded).toFixed(3).replace(/\.?0+$/, "") || "0";
  return `${sign}${magnitude}${unit}`;
}

/** VINES-OPS-003: line-level Harvest correction -- weight-only, no
 * population consequence of any kind (a vine plant's own living population
 * is never affected by correcting a raw harvested weight). Mirrors
 * `CorrectHarvestForm.tsx`'s own shape, minus every heads/population field.
 * Two modes: Replace with corrected weight, or Void this Gutter's
 * contribution entirely. `supersedes_correction_id` is always the line's
 * own `correction_tip_id` at render time -- a stale belief is a 409,
 * surfaced via `serverError` and forcing back to the values step. */
export function CorrectVinesHarvestForm({
  sourceLine,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  sourceLine: VinesHarvestSourceLineRead;
  onSubmit: (payload: CorrectVinesHarvestSourceLineCreate) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"values" | "review">("values");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);

  const {
    register, handleSubmit, watch, getValues, formState: { errors },
  } = useForm<CorrectVinesHarvestFormValues>({
    resolver: zodResolver(correctVinesHarvestFormSchema),
    defaultValues: {
      mode: "replace",
      current_harvested_weight_kg: Number(sourceLine.current_harvested_weight_kg),
      corrected_harvested_weight_kg: Number(sourceLine.current_harvested_weight_kg),
      reason_code: "", note: "",
    },
    mode: "onBlur",
  });

  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("values");
  }

  const mode = watch("mode");

  function goToReview(values: CorrectVinesHarvestFormValues) {
    void values;
    setStep("review");
  }

  async function confirm() {
    const values = getValues();
    const isVoid = values.mode === "void";
    const fingerprint = JSON.stringify({
      isVoid, corrected_harvested_weight_kg: isVoid ? null : values.corrected_harvested_weight_kg,
      reason_code: values.reason_code, note: values.note,
    });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: CorrectVinesHarvestSourceLineCreate = {
      client_command_id: idToUse,
      supersedes_correction_id: sourceLine.correction_tip_id,
      is_void: isVoid,
      corrected_harvested_weight_kg: isVoid ? null : String(values.corrected_harvested_weight_kg),
      reason_code: values.reason_code,
      note: values.note.trim(),
    };
    try {
      await onSubmit(payload);
      onCancel();
    } catch {
      // Server error is already surfaced via the `serverError` prop; keep
      // the form open so the operator can retry or adjust.
    }
  }

  const originalWeight = sourceLine.original_harvested_weight_kg;
  const currentWeight = sourceLine.current_harvested_weight_kg;

  if (step === "review") {
    const values = getValues();
    const isVoid = values.mode === "void";
    const correctedWeight = isVoid ? 0 : (values.corrected_harvested_weight_kg ?? 0);
    const weightDelta = correctedWeight - Number(currentWeight);
    return (
      <div className="flex flex-col gap-3 rounded-md border border-border-subtle bg-surface-subtle p-3">
        <h3 className="text-sm font-semibold text-ink">Review correction</h3>
        <dl className="grid grid-cols-3 gap-x-3 gap-y-2 text-sm">
          <div>
            <dt className="text-ink-muted">Original</dt>
            <dd className="text-ink">{originalWeight} kg</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Current effective</dt>
            <dd className="text-ink">{currentWeight} kg</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Corrected</dt>
            <dd className="text-ink">{isVoid ? "VOID — 0 kg" : `${correctedWeight} kg`}</dd>
          </div>
        </dl>
        <p className="text-sm text-ink">Net commercial adjustment: {signed(weightDelta, " kg")}</p>
        <p className="text-xs text-ink-muted">
          Never changes living plant count, Grow Bag capacity, or any biological state.
        </p>
        {serverError && <p role="alert" className={errorClass}>{correctionErrorMessage(serverError)}</p>}
        <div className="flex gap-2">
          <Button type="button" variant="secondary" onClick={() => setStep("values")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={confirm} disabled={isSubmitting}>
            {isSubmitting ? "Submitting…" : "Confirm correction"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit(goToReview)}
      className="flex flex-col gap-3 rounded-md border border-border-subtle bg-surface-subtle p-3"
    >
      <p className="text-sm text-ink-muted">Current effective: {currentWeight} kg</p>
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input type="radio" value="replace" {...register("mode")} />
          Replace with corrected weight
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" value="void" {...register("mode")} />
          Void this Gutter&apos;s contribution
        </label>
      </div>
      {mode === "replace" ? (
        <Field label="Raw harvested weight (kg)" error={errors.corrected_harvested_weight_kg?.message}>
          <input
            type="number" min={0.001} step={0.001} className={inputClass}
            {...register("corrected_harvested_weight_kg", { valueAsNumber: true })}
          />
        </Field>
      ) : (
        <p className="text-xs text-ink-muted">This source contribution becomes 0 kg.</p>
      )}
      <Field label="Reason" error={errors.reason_code?.message}>
        <select className={inputClass} {...register("reason_code")}>
          <option value="">Select a reason…</option>
          {HARVEST_CORRECTION_REASONS.map((r) => (
            <option key={r.code} value={r.code}>
              {r.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Note (required)" error={errors.note?.message}>
        <textarea className={`${inputClass} min-h-16`} rows={2} {...register("note")} />
      </Field>
      {serverError && <p role="alert" className={errorClass}>{correctionErrorMessage(serverError)}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          Review
        </Button>
      </div>
    </form>
  );
}
