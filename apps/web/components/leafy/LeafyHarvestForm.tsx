"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { HarvestablePlateRead, RecordLeafyHarvestCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  DEFAULT_LEAFY_HARVEST_LINE_FORM_VALUES,
  recordLeafyHarvestFormSchema,
  type RecordLeafyHarvestFormValues,
} from "@/lib/validation/leafyHarvest";

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

/** HARVEST-OPS-001 SLICE 2: "Record Harvest" -- one command, one CropBatch,
 * one or more Production Plate source rows, each with independent Heads
 * harvested / Raw harvested weight / note. Membership (which Plates are
 * included) is owned by the parent page (`HarvestablePlatesPanel`'s Add/
 * Remove) -- this component is remounted (via `key`) whenever that set
 * changes, so its own `useFieldArray` always initializes fresh from each
 * Plate's live `current_living_heads`, never a stale snapshot. Mirrors
 * `RecordPlantLossForm.tsx`'s configure -> review -> confirm shape, scaled
 * up to N independent lines (one CropBatch only, decision 10). */
export function LeafyHarvestForm({
  plates,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  plates: HarvestablePlateRead[];
  onSubmit: (payload: RecordLeafyHarvestCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const initial = nowDateAndTime();

  const {
    register, control, handleSubmit, getValues, formState: { errors },
  } = useForm<RecordLeafyHarvestFormValues>({
    resolver: zodResolver(recordLeafyHarvestFormSchema),
    defaultValues: {
      batch_id: plates[0]?.batch_id ?? "",
      batch_code: plates[0]?.batch_code ?? "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      note: "",
      lines: plates.map((p) => ({
        ...DEFAULT_LEAFY_HARVEST_LINE_FORM_VALUES,
        batch_carrier_assignment_id: p.current_batch_carrier_assignment_id,
        production_plate_code: p.production_plate_code,
        current_living_heads: p.current_living_heads,
      })),
    },
    mode: "onBlur",
  });
  const { fields } = useFieldArray({ control, name: "lines" });

  // Mirrors RecordPlantLossForm.tsx's own established 409 handling exactly.
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  function goToReview(values: RecordLeafyHarvestFormValues) {
    void values;
    setStep("review");
  }

  function confirm() {
    const values = getValues();
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const sourceLines = values.lines.map((line) => ({
      batch_carrier_assignment_id: line.batch_carrier_assignment_id,
      whole_unit_count: line.heads_harvested,
      harvested_weight_kg: String(line.raw_harvested_weight_kg),
      note: line.note.trim() || null,
    }));
    const fingerprint = JSON.stringify({
      batch_id: values.batch_id, effective_time: effectiveTime, note: values.note.trim() || null, sourceLines,
    });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: RecordLeafyHarvestCreate = {
      client_command_id: idToUse, batch_id: values.batch_id, effective_time: effectiveTime,
      produce_lot_code: `HL-${idToUse.slice(0, 8).toUpperCase()}`, note: values.note.trim() || null,
      source_lines: sourceLines,
    };
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    const totalHeads = values.lines.reduce((sum, l) => sum + (l.heads_harvested || 0), 0);
    const totalWeight = values.lines.reduce((sum, l) => sum + (l.raw_harvested_weight_kg || 0), 0);
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <h2 className="font-serif text-base font-semibold text-ink">Review before recording</h2>
        <p className="text-sm text-ink-muted">
          Batch <span className="font-medium text-ink">{values.batch_code}</span> · {values.effective_date}{" "}
          {values.effective_time_of_day}
        </p>
        <ul className="flex flex-col gap-3">
          {values.lines.map((line) => {
            const resulting = line.current_living_heads - line.heads_harvested;
            return (
              <li key={line.batch_carrier_assignment_id} className="rounded-md border border-border-subtle p-3 text-sm">
                <p className="font-medium text-ink">{line.production_plate_code}</p>
                <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1">
                  <div>
                    <dt className="text-ink-muted">Living before</dt>
                    <dd className="text-ink">{line.current_living_heads.toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-muted">Heads harvested</dt>
                    <dd className="text-ink">{line.heads_harvested.toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-muted">Expected living after</dt>
                    <dd className="text-ink">{resulting.toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-muted">Raw weight</dt>
                    <dd className="text-ink">{line.raw_harvested_weight_kg} kg</dd>
                  </div>
                </dl>
                {line.note && <p className="mt-1 text-xs text-ink-muted">Note: {line.note}</p>}
                {resulting === 0 && (
                  <p className="mt-1 text-xs text-ink-muted">Production population will be released.</p>
                )}
              </li>
            );
          })}
        </ul>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-md bg-surface-subtle p-3 text-sm">
          <div>
            <dt className="text-ink-muted">Total heads</dt>
            <dd className="font-medium text-ink">{totalHeads.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Total raw weight</dt>
            <dd className="font-medium text-ink">{totalWeight} kg</dd>
          </div>
        </dl>
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
      <h2 className="font-serif text-base font-semibold text-ink">Record Harvest — {plates[0]?.batch_code}</h2>

      <ul className="flex flex-col gap-3">
        {fields.map((field, index) => (
          <li key={field.id} className="rounded-md border border-border-subtle p-3">
            <p className="text-sm font-semibold text-ink">
              {field.production_plate_code} <span className="font-normal text-ink-muted">— Living{" "}
              {field.current_living_heads.toLocaleString()}</span>
            </p>
            <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Heads harvested" error={errors.lines?.[index]?.heads_harvested?.message}>
                <input
                  type="number" min={1} step={1} className={inputClass}
                  {...register(`lines.${index}.heads_harvested`, { valueAsNumber: true })}
                />
              </Field>
              <Field label="Raw harvested weight (kg)" error={errors.lines?.[index]?.raw_harvested_weight_kg?.message}>
                <input
                  type="number" min={0.001} step={0.001} className={inputClass}
                  {...register(`lines.${index}.raw_harvested_weight_kg`, { valueAsNumber: true })}
                />
              </Field>
              <Field label="Note (optional)">
                <input className={inputClass} {...register(`lines.${index}.note`)} />
              </Field>
            </div>
          </li>
        ))}
      </ul>
      {errors.lines?.root && <p className={errorClass}>{errors.lines.root.message}</p>}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-md bg-surface-subtle p-3 text-sm">
        <div>
          <dt className="text-ink-muted">Plates in this Harvest</dt>
          <dd className="font-medium text-ink">{fields.length}</dd>
        </div>
      </dl>

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
