"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { DispatchLineRow } from "@/components/processing/DispatchLineRow";
import { Button } from "@/components/ui/Button";
import type { DispatchEventCreate, FinishedGoodsLotRead } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { recordDispatchFormSchema, type RecordDispatchFormValues } from "@/lib/validation/dispatch";

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

/** PILOT-READY-001: "Record Dispatch" -- one or more Finished Goods Lots
 * (already selected by the parent page, same convention as
 * `PackingForm`'s `lots` prop), consuming each Lot's currently-unplaced
 * balance, plus exactly one dispatch-level temperature reading (the CMP
 * frozen rule: one Celsius reading per dispatch/vehicle, never per
 * line/lot/product/container -- it lives here, alongside code/effective
 * time/external reference/note, never inside `DispatchLineRow`). Mirrors
 * `PackingForm.tsx`'s configure -> review -> confirm shape and
 * idempotency-key discipline exactly. Remounted (via `key`) by the parent
 * whenever the selected Lot set changes. */
export function DispatchForm({
  farmId,
  lots,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  lots: FinishedGoodsLotRead[];
  onSubmit: (payload: DispatchEventCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const initial = nowDateAndTime();

  const {
    register, control, handleSubmit, getValues, setValue, formState: { errors },
  } = useForm<RecordDispatchFormValues>({
    resolver: zodResolver(recordDispatchFormSchema),
    defaultValues: {
      code: "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      dispatch_temperature_c: 0,
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
  const { fields } = useFieldArray({ control, name: "lines" });

  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  function goToReview(values: RecordDispatchFormValues) {
    void values;
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
      dispatch_temperature_c: String(values.dispatch_temperature_c),
      lines,
    };
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <StepIndicator step="review" />
        <h2 className="font-serif text-base font-semibold text-ink">Review before recording</h2>
        <p className="text-sm text-ink-muted">
          {values.code} · {values.effective_date} {values.effective_time_of_day}
        </p>
        {/* One reading for the whole vehicle/dispatch -- never per line/lot,
            so it is deliberately shown once here, apart from the per-lot
            list below, rather than folded into any one line's row. */}
        <p className="rounded-md border border-border-subtle bg-surface-subtle px-3 py-2 text-sm text-ink">
          Dispatch temperature: {values.dispatch_temperature_c} °C{" "}
          <span className="text-xs text-ink-muted">— one reading for this entire dispatch</span>
        </p>
        <ul className="flex flex-col gap-2">
          {values.lines.map((l) => (
            <li key={l.finished_goods_lot_id} className="rounded-md border border-border-subtle p-3 text-sm">
              <span className="font-medium text-ink">{l.finished_goods_lot_code}</span>{" "}
              <span className="text-ink-muted">
                — {l.dispatched_weight_kg} kg / {l.dispatched_package_count} pkg
              </span>
            </li>
          ))}
        </ul>
        {values.external_reference && (
          <p className="text-sm text-ink-muted">
            Reference: <span className="text-ink">{values.external_reference}</span>
          </p>
        )}
        {values.note && (
          <p className="text-sm text-ink-muted">
            Note: <span className="text-ink">{values.note}</span>
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
      className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4"
    >
      <StepIndicator step="configure" />
      <h2 className="font-serif text-base font-semibold text-ink">Dispatch {lots.map((l) => l.code).join(", ")}</h2>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink">Finished Goods Lots</h3>
        <ul className="flex flex-col gap-3">
          {fields.map((field, index) => (
            <DispatchLineRow key={field.id} farmId={farmId} lot={lots[index]} index={index} register={register} setValue={setValue} errors={errors} />
          ))}
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
      <div className="rounded-md border border-border-subtle bg-surface-subtle p-3">
        <Field label="Dispatch Temperature (°C)" error={errors.dispatch_temperature_c?.message}>
          <input
            type="number" step={0.1} className={inputClass}
            {...register("dispatch_temperature_c", { valueAsNumber: true })}
          />
        </Field>
        <p className="mt-1 text-xs text-ink-muted">One reading for this entire dispatch — not per Lot or container.</p>
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
    <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">
      Step {step === "configure" ? "1" : "2"} of 2 · {step === "configure" ? "Configure" : "Review"}
    </p>
  );
}
