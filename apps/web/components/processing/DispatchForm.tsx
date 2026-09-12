"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { DispatchLineRow } from "@/components/processing/DispatchLineRow";
import { Button } from "@/components/ui/Button";
import type { DispatchEventCreate, FinishedGoodsLotRead } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { recordDispatchFormSchema, type RecordDispatchFormValues } from "@/lib/validation/dispatch";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-sm font-medium text-wl-text";
const errorClass = "text-xs text-wl-flag-fg";

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

/** PILOT-READY-001: "Record Dispatch" -- one or more Finished Goods Lots
 * (already selected by the parent page, same convention as
 * `PackingForm`'s `lots` prop), consuming each Lot's currently-unplaced
 * balance, plus exactly one dispatch-level temperature reading (the CMP
 * frozen rule: one Celsius reading per dispatch/vehicle, never per
 * line/lot/product/container -- it lives here, alongside code/effective
 * time/external reference/note, never inside `DispatchLineRow`). Mirrors
 * `PackingForm.tsx`'s configure -> review -> confirm shape and
 * idempotency-key discipline exactly.
 *
 * PILOT-UX-003: no longer remounted when the selected Lot set changes (the
 * parent used to pass `key={selectedIds.join(",")}`, which wiped the
 * dispatch code, temperature, date/time, note and every already-edited
 * line on every add/remove). This form stays mounted for the life of the
 * draft and the effect below reconciles `lines` to the `lots` prop by id --
 * mirrors `PackingForm.tsx`'s own `input_lines` reconciliation exactly. */
export function DispatchForm({
  farmId,
  lots,
  onRemoveLot,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  lots: FinishedGoodsLotRead[];
  onRemoveLot: (lotId: string) => void;
  onSubmit: (payload: DispatchEventCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  // State, not a ref: written from `goToReview`, which is passed inline to
  // `handleSubmit()` in the JSX below -- the React Compiler correctly
  // refuses to let a function constructed during render write a ref.
  const [reviewedLotIdsKey, setReviewedLotIdsKey] = useState<string | null>(null);
  const initial = nowDateAndTime();

  const {
    register, control, handleSubmit, getValues, setValue, formState: { errors },
  } = useForm<RecordDispatchFormValues>({
    resolver: zodResolver(recordDispatchFormSchema),
    defaultValues: {
      code: "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      // PILOT-UX-003: starts blank, never a prefilled `0` -- 0 °C is a real,
      // plausible reading, so a numeric default here would silently pass as
      // "measured" if the operator never touches the field.
      dispatch_temperature_c: null,
      external_reference: "",
      note: "",
      lines: lots.map((lot) => ({
        finished_goods_lot_id: lot.id,
        finished_goods_lot_code: lot.code,
        available_weight_kg: 0,
        available_package_count: 0,
        dispatched_weight_kg: 0,
        dispatched_package_count: 0,
      })),
    },
    mode: "onBlur",
  });
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const lotIdsKey = lots.map((l) => l.id).join(",");
  const lotById = useMemo(() => new Map(lots.map((lot) => [lot.id, lot])), [lots]);

  // Reconcile `lines` to the current `lots` prop by id, in place -- never a
  // full reset. Removals first, then append exactly the Lots not already
  // represented (mirrors `PackingForm.tsx`'s identical effect).
  useEffect(() => {
    const propIds = lots.map((l) => l.id);
    const current = getValues("lines");
    const removeIndices = current.reduce<number[]>((acc, line, idx) => {
      if (!propIds.includes(line.finished_goods_lot_id)) acc.push(idx);
      return acc;
    }, []);
    if (removeIndices.length > 0) remove(removeIndices);
    const remainingIds = current
      .filter((_, idx) => !removeIndices.includes(idx))
      .map((line) => line.finished_goods_lot_id);
    for (const lot of lots) {
      if (remainingIds.includes(lot.id)) continue;
      append({
        finished_goods_lot_id: lot.id,
        finished_goods_lot_code: lot.code,
        available_weight_kg: 0,
        available_package_count: 0,
        dispatched_weight_kg: 0,
        dispatched_package_count: 0,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotIdsKey]);

  // Never show a stale Review: if the selected-Lot set changes while the
  // operator is on Review, drop back to Configure so totals/lines are
  // always recomputed from the current selection, never a frozen snapshot
  // (ticket: "If source selection changes while user is on Review: return
  // to Editing and recompute Review"). Adjusted directly during render
  // (React's own blessed pattern, mirrors the identical `prevServerError`
  // guard just below) rather than in an effect, which would cause an extra,
  // avoidable cascading render.
  const [prevLotIdsKeyForStaleCheck, setPrevLotIdsKeyForStaleCheck] = useState(lotIdsKey);
  if (lotIdsKey !== prevLotIdsKeyForStaleCheck) {
    setPrevLotIdsKeyForStaleCheck(lotIdsKey);
    if (step === "review" && reviewedLotIdsKey !== null && reviewedLotIdsKey !== lotIdsKey) {
      setStep("configure");
    }
  }

  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  function goToReview(values: RecordDispatchFormValues) {
    void values;
    setReviewedLotIdsKey(lotIdsKey);
    setStep("review");
  }

  function confirm() {
    const values = getValues();
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const lines = values.lines.map((l) => ({
      finished_goods_lot_id: l.finished_goods_lot_id,
      dispatched_weight_kg: String(l.dispatched_weight_kg),
      dispatched_package_count: l.dispatched_package_count,
    }));
    const fingerprint = JSON.stringify({ values, lines });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: DispatchEventCreate = {
      client_command_id: idToUse,
      effective_time: effectiveTime,
      code: values.code.trim().toUpperCase(),
      external_reference: values.external_reference.trim() || null,
      note: values.note.trim() || null,
      // Non-null by construction: `confirm` is only reachable via Review,
      // which the schema's `superRefine` blocks entering while this is null.
      dispatch_temperature_c: String(values.dispatch_temperature_c as number),
      lines,
    };
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <StepIndicator step="review" />
        <h2 className="font-serif text-base font-semibold text-wl-text">Review before recording</h2>
        <p className="text-sm text-wl-text-secondary">
          {values.code} · {values.effective_date} {values.effective_time_of_day}
        </p>
        {/* One reading for the whole vehicle/dispatch -- never per line/lot,
            so it is deliberately shown once here, apart from the per-lot
            list below, rather than folded into any one line's row. */}
        <p className="rounded-md border border-wl-border bg-wl-surface-sunken px-3 py-2 text-sm text-wl-text">
          Dispatch temperature: {values.dispatch_temperature_c} °C{" "}
          <span className="text-xs text-wl-text-secondary">— one reading for this entire dispatch</span>
        </p>
        <ul className="flex flex-col gap-2">
          {values.lines.map((l) => (
            <li key={l.finished_goods_lot_id} className="rounded-md border border-wl-border p-3 text-sm">
              <span className="font-medium text-wl-text">{l.finished_goods_lot_code}</span>{" "}
              <span className="text-wl-text-secondary">
                — {l.dispatched_weight_kg} kg / {l.dispatched_package_count} pkg
              </span>
            </li>
          ))}
        </ul>
        {values.external_reference && (
          <p className="text-sm text-wl-text-secondary">
            Reference: <span className="text-wl-text">{values.external_reference}</span>
          </p>
        )}
        {values.note && (
          <p className="text-sm text-wl-text-secondary">
            Note: <span className="text-wl-text">{values.note}</span>
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
    <form
      onSubmit={handleSubmit(goToReview)}
      className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4"
    >
      <StepIndicator step="configure" />
      <h2 className="font-serif text-base font-semibold text-wl-text">Dispatch {lots.map((l) => l.code).join(", ")}</h2>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-wl-text">Finished Goods Lots</h3>
        <ul className="flex flex-col gap-3">
          {fields.map((field, index) => {
            const lot = lotById.get(field.finished_goods_lot_id);
            if (!lot) return null;
            return (
              <DispatchLineRow
                key={field.id} farmId={farmId} lot={lot} index={index} register={register} setValue={setValue}
                errors={errors} onRemove={() => onRemoveLot(lot.id)}
              />
            );
          })}
        </ul>
        {typeof errors.lines?.message === "string" && <p className={errorClass}>{errors.lines.message}</p>}
        {errors.lines?.root && <p className={errorClass}>{errors.lines.root.message}</p>}
      </div>

      <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Dispatch code" error={errors.code?.message}>
          <input className={inputClass} {...register("code")} />
        </Field>
        <Field label="External reference (optional)" error={errors.external_reference?.message}>
          <input className={inputClass} {...register("external_reference")} />
        </Field>
      </fieldset>

      {/* Deliberately its own bordered block, separate from the code/
          reference fieldset above -- this is the single reading for the
          whole vehicle/dispatch (never per Lot/line/container), so it reads
          as one distinct fact rather than just another form field. */}
      <div className="rounded-md border border-wl-border bg-wl-surface-sunken p-3">
        <Field label="Dispatch Temperature (°C)" error={errors.dispatch_temperature_c?.message}>
          <input
            type="number" step={0.1} className={inputClass} placeholder="Enter the measured reading"
            {...register("dispatch_temperature_c", {
              // `Number(null) === 0` -- guard both the DOM's blank-string
              // read and the raw default value, or an untouched field would
              // silently validate as a fabricated 0 °C reading.
              setValueAs: (v) => (v === "" || v === null || v === undefined ? null : Number(v)),
            })}
          />
        </Field>
        <p className="mt-1 text-xs text-wl-text-secondary">One reading for this entire dispatch — not per Lot or container.</p>
      </div>

      <Field label="Note (optional)" error={errors.note?.message}>
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

/** Purely presentational -- both steps already exist as real form/review
 * state (`step` above); this just makes the two-step configure → review
 * flow visible to the operator, mirroring `PackingForm.tsx`'s own
 * `StepIndicator`. */
function StepIndicator({ step }: { step: "configure" | "review" }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wide text-wl-brand">
      Step {step === "configure" ? "1" : "2"} of 2 · {step === "configure" ? "Configure" : "Review"}
    </p>
  );
}
