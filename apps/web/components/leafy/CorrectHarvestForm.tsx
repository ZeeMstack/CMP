"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CorrectLeafyHarvestSourceLineCreate, LeafyHarvestSourceLineRead } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  correctLeafyHarvestFormSchema, HARVEST_CORRECTION_REASONS, type CorrectLeafyHarvestFormValues,
} from "@/lib/validation/leafyHarvest";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

// SLICE 2 CORRECTION 1: branch on the backend's stable `error.code`, never
// on the shape/content of `error.message` -- human-readable text is not a
// machine contract. `HARVEST_CORRECTION_STALE` gets its own required
// operator-facing wording; every other Harvest conflict code
// (`HARVEST_NEGATIVE_LOT_BALANCE`, `HARVEST_QUALITY_HOLD`,
// `HARVEST_POPULATION_CONFLICT`, `HARVEST_CARRIER_REUSED`) carries the
// backend's own message as the intended operator-facing sentence already
// (never replaced by `friendlyMutationErrorMessage`'s generic canned
// conflict text). A conflict with no recognized code (or a different
// `kind` entirely) falls back to the shared generic messaging.
const HARVEST_CORRECTION_STALE_MESSAGE =
  "This Harvest line was corrected by someone else. Refresh and review the latest values before trying again.";

function correctionErrorMessage(error: AppError): string {
  if (error.code === "HARVEST_CORRECTION_STALE") return HARVEST_CORRECTION_STALE_MESSAGE;
  if (
    error.kind === "conflict"
    && (error.code === "HARVEST_NEGATIVE_LOT_BALANCE"
      || error.code === "HARVEST_QUALITY_HOLD"
      || error.code === "HARVEST_POPULATION_CONFLICT"
      || error.code === "HARVEST_CARRIER_REUSED")
  ) {
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

/** Display-only: rounds to this UI's own 3-decimal weight precision to
 * absorb IEEE-754 float noise (e.g. `1.2 - 0.5 === 0.7000000000000002`
 * in JS) and strips unnecessary trailing zeros -- never changes the
 * underlying correction payload or the arithmetic sent to the backend,
 * only how the "Net commercial adjustment" delta is rendered. Also used
 * for the (always-integer) heads delta, where rounding/stripping is a
 * no-op. `Math.round(n * 1000) / 1000 || 0` collapses a `-0` result
 * (e.g. equal weights) to `0` so the sign is never shown for a true zero. */
export function signed(n: number, unit: string): string {
  const rounded = Math.round(n * 1000) / 1000 || 0;
  const sign = rounded > 0 ? "+" : rounded < 0 ? "-" : "";
  const magnitude = Math.abs(rounded).toFixed(3).replace(/\.?0+$/, "") || "0";
  return `${sign}${magnitude}${unit}`;
}

/** Biology is driven ONLY by head count, never weight (a weight-only
 * correction leaves Production population untouched). `biologicalDelta` is
 * `corrected_effective_heads - current_effective_heads` (VOID counts as
 * 0 corrected heads). Positive: more heads now claimed than before, so
 * MORE Production plants are newly consumed. Negative: fewer heads now
 * claimed than before, so the difference is restored back onto the source
 * Plate. Zero: no biological population change at all. */
function biologicalPopulationMessage(biologicalDelta: number): string {
  if (biologicalDelta > 0) {
    const plural = biologicalDelta === 1 ? "plant" : "plants";
    return `This correction will consume ${biologicalDelta} additional Production ${plural} from the source Plate. The physical Plate itself does not move.`;
  }
  if (biologicalDelta < 0) {
    const n = Math.abs(biologicalDelta);
    const plural = n === 1 ? "plant" : "plants";
    return `This correction will restore ${n} Production ${plural} on the source Plate. The physical Plate itself does not move.`;
  }
  return "This correction does not change Production population. The physical Plate itself does not move.";
}

/** HARVEST-OPS-001 SLICE 2: line-level Harvest correction -- action label is
 * always "Correct Harvest", even when the current state is VOID (never
 * "Un-void", ticket section Q). Two modes: Replace with corrected Harvest,
 * or Void Harvest contribution. `supersedes_correction_id` is always the
 * line's own `correction_tip_id` at render time -- the caller's belief
 * about the current chain tip; a stale belief is a 409, surfaced via
 * `serverError` and forcing back to the values step (mirrors
 * RecordPlantLossForm.tsx's own 409 handling exactly). */
export function CorrectHarvestForm({
  sourceLine,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  sourceLine: LeafyHarvestSourceLineRead;
  onSubmit: (payload: CorrectLeafyHarvestSourceLineCreate) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"values" | "review">("values");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);

  const {
    register, handleSubmit, watch, getValues, formState: { errors },
  } = useForm<CorrectLeafyHarvestFormValues>({
    resolver: zodResolver(correctLeafyHarvestFormSchema),
    defaultValues: {
      mode: "replace",
      current_whole_unit_count: sourceLine.current_whole_unit_count,
      current_harvested_weight_kg: Number(sourceLine.current_harvested_weight_kg),
      corrected_whole_unit_count: sourceLine.current_whole_unit_count,
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

  function goToReview(values: CorrectLeafyHarvestFormValues) {
    void values;
    setStep("review");
  }

  async function confirm() {
    const values = getValues();
    const isVoid = values.mode === "void";
    const fingerprint = JSON.stringify({
      isVoid,
      corrected_whole_unit_count: isVoid ? null : values.corrected_whole_unit_count,
      corrected_harvested_weight_kg: isVoid ? null : values.corrected_harvested_weight_kg,
      reason_code: values.reason_code, note: values.note,
    });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: CorrectLeafyHarvestSourceLineCreate = {
      client_command_id: idToUse,
      supersedes_correction_id: sourceLine.correction_tip_id,
      is_void: isVoid,
      corrected_harvested_weight_kg: isVoid ? null : String(values.corrected_harvested_weight_kg),
      corrected_whole_unit_count: isVoid ? null : (values.corrected_whole_unit_count ?? null),
      reason_code: values.reason_code,
      note: values.note.trim(),
    };
    try {
      await onSubmit(payload);
      onCancel(); // success -- close the inline form; the corrected line and
      // its history entry now both appear in the same History panel once refetched.
    } catch {
      // Server error is already surfaced via the `serverError` prop; keep
      // the form open so the operator can retry or adjust.
    }
  }

  const originalHeads = sourceLine.original_whole_unit_count;
  const originalWeight = sourceLine.original_harvested_weight_kg;
  const currentHeads = sourceLine.current_whole_unit_count;
  const currentWeight = sourceLine.current_harvested_weight_kg;

  if (step === "review") {
    const values = getValues();
    const isVoid = values.mode === "void";
    const correctedHeads = isVoid ? 0 : (values.corrected_whole_unit_count ?? 0);
    const correctedWeight = isVoid ? 0 : (values.corrected_harvested_weight_kg ?? 0);
    const headsDelta = correctedHeads - currentHeads;
    const weightDelta = correctedWeight - Number(currentWeight);
    return (
      <div className="flex flex-col gap-3 rounded-md border border-border-subtle bg-surface-subtle p-3">
        <h3 className="text-sm font-semibold text-ink">Review correction</h3>
        <dl className="grid grid-cols-3 gap-x-3 gap-y-2 text-sm">
          <div>
            <dt className="text-ink-muted">Original</dt>
            <dd className="text-ink">
              {originalHeads ?? "—"} heads / {originalWeight} kg
            </dd>
          </div>
          <div>
            <dt className="text-ink-muted">Current effective</dt>
            <dd className="text-ink">
              {currentHeads} heads / {currentWeight} kg
            </dd>
          </div>
          <div>
            <dt className="text-ink-muted">Corrected</dt>
            <dd className="text-ink">
              {isVoid ? "VOID — 0 heads / 0 kg" : `${correctedHeads} heads / ${correctedWeight} kg`}
            </dd>
          </div>
        </dl>
        <p className="text-sm text-ink">
          Net commercial adjustment: {signed(headsDelta, " heads")} · {signed(weightDelta, " kg")}
        </p>
        <p className="text-xs text-ink-muted">{biologicalPopulationMessage(headsDelta)}</p>
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
      <p className="text-sm text-ink-muted">
        Current effective: {currentHeads} heads / {currentWeight} kg
      </p>
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input type="radio" value="replace" {...register("mode")} />
          Replace with corrected Harvest
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" value="void" {...register("mode")} />
          Void Harvest contribution
        </label>
      </div>
      {mode === "replace" ? (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Heads harvested" error={errors.corrected_whole_unit_count?.message}>
            <input
              type="number" min={1} step={1} className={inputClass}
              {...register("corrected_whole_unit_count", { valueAsNumber: true })}
            />
          </Field>
          <Field label="Raw harvested weight (kg)" error={errors.corrected_harvested_weight_kg?.message}>
            <input
              type="number" min={0.001} step={0.001} className={inputClass}
              {...register("corrected_harvested_weight_kg", { valueAsNumber: true })}
            />
          </Field>
        </div>
      ) : (
        <p className="text-xs text-ink-muted">
          This source contribution becomes 0 heads / 0 kg. {biologicalPopulationMessage(-currentHeads)}
        </p>
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
