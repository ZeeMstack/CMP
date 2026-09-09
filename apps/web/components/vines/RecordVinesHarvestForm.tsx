"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { RecordVinesHarvestCreate, VinesHarvestableSourceRead } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  DEFAULT_VINES_HARVEST_LINE_FORM_VALUES,
  recordVinesHarvestFormSchema,
  type RecordVinesHarvestFormValues,
} from "@/lib/validation/vinesHarvest";

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

/** VINES-OPS-003: "Record harvest" -- one command, one CropBatch, one or
 * more Grow Gutter source rows, each with an independent raw harvested
 * weight (never a per-Bag/per-plant split -- ticket's own frozen compact
 * UX: "Gutter | Raw weight"). Weight-only, no heads/count field anywhere.
 * Membership (which Gutters are included) is owned by the parent page
 * (`VinesHarvestableSourcesPanel`'s Add/Remove) -- this component is
 * remounted (via `key`) whenever that set changes. Mirrors `LeafyHarvestForm.
 * tsx`'s configure -> review -> confirm shape exactly, scaled to N
 * independent Gutter lines (one CropBatch only). */
export function RecordVinesHarvestForm({
  sources,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  sources: VinesHarvestableSourceRead[];
  onSubmit: (payload: RecordVinesHarvestCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const initial = nowDateAndTime();

  const {
    register, control, handleSubmit, getValues, formState: { errors },
  } = useForm<RecordVinesHarvestFormValues>({
    resolver: zodResolver(recordVinesHarvestFormSchema),
    defaultValues: {
      batch_id: sources[0]?.batch_id ?? "",
      batch_code: sources[0]?.batch_code ?? "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      note: "",
      lines: sources.map((s) => ({
        ...DEFAULT_VINES_HARVEST_LINE_FORM_VALUES,
        gutter_id: s.gutter_id, gutter_code: s.gutter_code, living_plant_count: s.living_plant_count,
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

  function goToReview(values: RecordVinesHarvestFormValues) {
    void values;
    setStep("review");
  }

  function confirm() {
    const values = getValues();
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const sourceLines = values.lines.map((line) => ({
      gutter_id: line.gutter_id, harvested_weight_kg: String(line.harvested_weight_kg),
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
    const payload: RecordVinesHarvestCreate = {
      client_command_id: idToUse, batch_id: values.batch_id, effective_time: effectiveTime,
      produce_lot_code: `VH-${idToUse.slice(0, 8).toUpperCase()}`, note: values.note.trim() || null,
      source_lines: sourceLines,
    };
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    const totalWeight = values.lines.reduce((sum, l) => sum + (l.harvested_weight_kg || 0), 0);
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <h2 className="font-serif text-base font-semibold text-ink">Review before recording</h2>
        <p className="text-sm text-ink-muted">
          Batch <span className="font-medium text-ink">{values.batch_code}</span> · {values.effective_date}{" "}
          {values.effective_time_of_day}
        </p>
        <ul className="flex flex-col gap-3">
          {values.lines.map((line) => (
            <li key={line.gutter_id} className="rounded-md border border-border-subtle p-3 text-sm">
              <p className="font-medium text-ink">{line.gutter_code}</p>
              <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1">
                <div>
                  <dt className="text-ink-muted">Living plants</dt>
                  <dd className="text-ink">{line.living_plant_count.toLocaleString()}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Raw weight</dt>
                  <dd className="text-ink">{line.harvested_weight_kg} kg</dd>
                </div>
              </dl>
              {line.note && <p className="mt-1 text-xs text-ink-muted">Note: {line.note}</p>}
            </li>
          ))}
        </ul>
        <dl className="rounded-md bg-surface-subtle p-3 text-sm">
          <div>
            <dt className="text-ink-muted">Total raw harvest</dt>
            <dd className="text-base font-semibold text-ink">{totalWeight} kg</dd>
          </div>
        </dl>
        <p className="text-xs text-ink-muted">
          Harvest never changes living plant count or Grow Bag capacity -- the same Gutter remains fully
          harvestable again later (repeat harvest).
        </p>
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
      <h2 className="font-serif text-base font-semibold text-ink">Record Harvest — {sources[0]?.batch_code}</h2>

      <ul className="flex flex-col gap-3">
        {fields.map((field, index) => (
          <li key={field.id} className="rounded-md border border-border-subtle p-3">
            <p className="text-sm font-semibold text-ink">
              {field.gutter_code}{" "}
              <span className="font-normal text-ink-muted">— Living {field.living_plant_count.toLocaleString()}</span>
            </p>
            <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Raw weight (kg)" error={errors.lines?.[index]?.harvested_weight_kg?.message}>
                <input
                  type="number" min={0.001} step={0.001} className={inputClass}
                  {...register(`lines.${index}.harvested_weight_kg`, { valueAsNumber: true })}
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
          <dt className="text-ink-muted">Gutters in this Harvest</dt>
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
          Review harvest
        </Button>
      </div>
    </form>
  );
}
