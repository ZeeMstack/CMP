"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { GradingOutputRow } from "@/components/processing/GradingOutputRow";
import { LocationSelect } from "@/components/processing/LocationSelect";
import { ReconciliationSummary } from "@/components/processing/ReconciliationSummary";
import type { GradingEventCreate, HarvestedProduceLotRead, LocationTreeNode, ProduceLotBalanceRead } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  DEFAULT_GRADING_OUTPUT_FORM_VALUES,
  recordGradingFormSchema,
  type RecordGradingFormValues,
} from "@/lib/validation/grading";

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

/** POSTHARVEST-OPS-001G: "Record Grading" -- one source Harvested Produce
 * Lot, full weight/count reconciliation (rejection/loss/sample/remainder),
 * one or more Graded Produce Lot outputs. Mirrors `LeafyHarvestForm.tsx`'s
 * configure -> review -> confirm shape and idempotency-key discipline
 * exactly. Remounted (via `key`) by the parent whenever the selected source
 * Lot changes, so defaults always reflect the current selection. */
export function GradingForm({
  sourceLot,
  balance,
  locations,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  sourceLot: HarvestedProduceLotRead;
  balance: ProduceLotBalanceRead | undefined;
  locations: LocationTreeNode[];
  onSubmit: (payload: GradingEventCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const initial = nowDateAndTime();
  const hasCounts = sourceLot.total_whole_unit_count != null;

  const {
    register, control, handleSubmit, getValues, setValue, watch, formState: { errors },
  } = useForm<RecordGradingFormValues>({
    resolver: zodResolver(recordGradingFormSchema),
    defaultValues: {
      source_harvested_produce_lot_id: sourceLot.id,
      source_produce_lot_code: sourceLot.code,
      processing_hall_location_id: "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      note: "",
      count_mode: hasCounts,
      input_presented_weight_kg: Number(balance?.available_weight_kg ?? sourceLot.total_harvested_weight_kg),
      input_presented_whole_unit_count: balance?.available_whole_unit_count ?? sourceLot.total_whole_unit_count ?? undefined,
      rejected_weight_kg: 0,
      rejected_whole_unit_count: hasCounts ? 0 : undefined,
      loss_weight_kg: 0,
      loss_whole_unit_count: hasCounts ? 0 : undefined,
      sample_weight_kg: 0,
      sample_whole_unit_count: hasCounts ? 0 : undefined,
      remainder_weight_kg: 0,
      remainder_whole_unit_count: hasCounts ? 0 : undefined,
      outputs: [{ ...DEFAULT_GRADING_OUTPUT_FORM_VALUES }],
    },
    mode: "onBlur",
  });
  const { fields, append, remove } = useFieldArray({ control, name: "outputs" });

  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  const watched = watch();
  const outputWeightSum = watched.outputs.reduce((sum, o) => sum + (o.output_weight_kg || 0), 0);
  // PRE-COMMIT CORRECTION: recomputed on every render from the watched
  // Date/Time fields, so editing either one re-filters each output row's
  // Version picker (see `GradingOutputRow`'s own effect) to what's
  // historically valid at this exact transaction time -- never a value
  // frozen from when the form first mounted.
  const effectiveTimeIso = (() => {
    if (!watched.effective_date || !watched.effective_time_of_day) return "";
    const parsed = new Date(`${watched.effective_date}T${watched.effective_time_of_day}`);
    return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString();
  })();

  function goToReview(values: RecordGradingFormValues) {
    void values;
    setStep("review");
  }

  function confirm() {
    const values = getValues();
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const outputs = values.outputs.map((o) => ({
      grade_definition_version_id: o.grade_definition_version_id,
      code: o.code.trim().toUpperCase(),
      output_weight_kg: String(o.output_weight_kg),
      output_whole_unit_count: values.count_mode ? o.output_whole_unit_count ?? null : null,
    }));
    const fingerprint = JSON.stringify({ values, outputs });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: GradingEventCreate = {
      client_command_id: idToUse,
      source_harvested_produce_lot_id: values.source_harvested_produce_lot_id,
      processing_hall_location_id: values.processing_hall_location_id,
      effective_time: effectiveTime,
      note: values.note.trim() || null,
      input_presented_weight_kg: String(values.input_presented_weight_kg),
      input_presented_whole_unit_count: values.count_mode ? values.input_presented_whole_unit_count ?? null : null,
      rejected_weight_kg: String(values.rejected_weight_kg),
      rejected_whole_unit_count: values.count_mode ? values.rejected_whole_unit_count ?? null : null,
      loss_weight_kg: String(values.loss_weight_kg),
      loss_whole_unit_count: values.count_mode ? values.loss_whole_unit_count ?? null : null,
      sample_weight_kg: String(values.sample_weight_kg),
      sample_whole_unit_count: values.count_mode ? values.sample_whole_unit_count ?? null : null,
      remainder_weight_kg: String(values.remainder_weight_kg),
      remainder_whole_unit_count: values.count_mode ? values.remainder_whole_unit_count ?? null : null,
      outputs,
    };
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    return (
      <div className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4">
        <h2 className="text-sm font-semibold text-ink">Review before recording</h2>
        <p className="text-sm text-ink-muted">
          Source <span className="font-medium text-ink">{values.source_produce_lot_code}</span> ·{" "}
          {values.effective_date} {values.effective_time_of_day}
        </p>
        <ReconciliationSummary
          inputLabel="Input presented"
          inputValue={values.input_presented_weight_kg}
          unit="kg"
          parts={[
            { label: "Rejected", value: values.rejected_weight_kg },
            { label: "Loss", value: values.loss_weight_kg },
            { label: "Sample", value: values.sample_weight_kg },
            { label: "Remainder", value: values.remainder_weight_kg },
            { label: "Graded outputs", value: outputWeightSum },
          ]}
        />
        <ul className="flex flex-col gap-2">
          {values.outputs.map((o) => (
            <li key={o.code} className="rounded-md border border-border-subtle p-3 text-sm">
              <p className="font-medium text-ink">
                {o.code} <span className="font-normal text-ink-muted">— {o.grade_definition_label}</span>
              </p>
              <p className="text-ink-muted">
                {o.output_weight_kg} kg{values.count_mode ? ` / ${o.output_whole_unit_count ?? "—"} units` : ""}
              </p>
            </li>
          ))}
        </ul>
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
            onClick={confirm}
            disabled={isSubmitting}
            className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
          >
            {isSubmitting ? "Recording…" : "Confirm"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit(goToReview)}
      className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h2 className="text-sm font-semibold text-ink">Grade {sourceLot.code}</h2>
      <p className="text-xs text-ink-muted">
        {sourceLot.crop.common_name}
        {sourceLot.variety ? ` / ${sourceLot.variety.name}` : ""} · Available{" "}
        {balance ? `${balance.available_weight_kg} kg` : `${sourceLot.total_harvested_weight_kg} kg (loading balance…)`}
        {hasCounts && balance ? ` / ${balance.available_whole_unit_count} units` : ""}
      </p>

      <Field label="Processing location" error={errors.processing_hall_location_id?.message}>
        <LocationSelect
          nodes={locations}
          value={watch("processing_hall_location_id")}
          onChange={(id) => setValue("processing_hall_location_id", id)}
        />
      </Field>

      <fieldset className="grid grid-cols-2 gap-3">
        <Field label="Input presented weight (kg)" error={errors.input_presented_weight_kg?.message}>
          <input
            type="number" min={0.001} step={0.001} className={inputClass}
            {...register("input_presented_weight_kg", { valueAsNumber: true })}
          />
        </Field>
        {watched.count_mode && (
          <Field label="Input presented count" error={errors.input_presented_whole_unit_count?.message}>
            <input
              type="number" min={1} step={1} className={inputClass}
              {...register("input_presented_whole_unit_count", { valueAsNumber: true })}
            />
          </Field>
        )}
      </fieldset>

      <fieldset className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Rejected (kg)" error={errors.rejected_weight_kg?.message}>
          <input type="number" min={0} step={0.001} className={inputClass} {...register("rejected_weight_kg", { valueAsNumber: true })} />
        </Field>
        <Field label="Loss (kg)" error={errors.loss_weight_kg?.message}>
          <input type="number" min={0} step={0.001} className={inputClass} {...register("loss_weight_kg", { valueAsNumber: true })} />
        </Field>
        <Field label="Sample (kg)" error={errors.sample_weight_kg?.message}>
          <input type="number" min={0} step={0.001} className={inputClass} {...register("sample_weight_kg", { valueAsNumber: true })} />
        </Field>
        <Field label="Remainder (kg)" error={errors.remainder_weight_kg?.message}>
          <input type="number" min={0} step={0.001} className={inputClass} {...register("remainder_weight_kg", { valueAsNumber: true })} />
        </Field>
        {watched.count_mode && (
          <>
            <Field label="Rejected (count)" error={errors.rejected_whole_unit_count?.message}>
              <input type="number" min={0} step={1} className={inputClass} {...register("rejected_whole_unit_count", { valueAsNumber: true })} />
            </Field>
            <Field label="Loss (count)" error={errors.loss_whole_unit_count?.message}>
              <input type="number" min={0} step={1} className={inputClass} {...register("loss_whole_unit_count", { valueAsNumber: true })} />
            </Field>
            <Field label="Sample (count)" error={errors.sample_whole_unit_count?.message}>
              <input type="number" min={0} step={1} className={inputClass} {...register("sample_whole_unit_count", { valueAsNumber: true })} />
            </Field>
            <Field label="Remainder (count)" error={errors.remainder_whole_unit_count?.message}>
              <input type="number" min={0} step={1} className={inputClass} {...register("remainder_whole_unit_count", { valueAsNumber: true })} />
            </Field>
          </>
        )}
      </fieldset>

      <ReconciliationSummary
        inputLabel="Input presented"
        inputValue={watched.input_presented_weight_kg || 0}
        unit="kg"
        parts={[
          { label: "Rejected", value: watched.rejected_weight_kg || 0 },
          { label: "Loss", value: watched.loss_weight_kg || 0 },
          { label: "Sample", value: watched.sample_weight_kg || 0 },
          { label: "Remainder", value: watched.remainder_weight_kg || 0 },
          { label: "Graded outputs", value: outputWeightSum },
        ]}
      />
      {watched.count_mode && (
        <ReconciliationSummary
          inputLabel="Input presented"
          inputValue={watched.input_presented_whole_unit_count || 0}
          unit="units"
          parts={[
            { label: "Rejected", value: watched.rejected_whole_unit_count || 0 },
            { label: "Loss", value: watched.loss_whole_unit_count || 0 },
            { label: "Sample", value: watched.sample_whole_unit_count || 0 },
            { label: "Remainder", value: watched.remainder_whole_unit_count || 0 },
            { label: "Graded outputs", value: watched.outputs.reduce((sum, o) => sum + (o.output_whole_unit_count || 0), 0) },
          ]}
        />
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink">Graded outputs</h3>
        <ul className="flex flex-col gap-3">
          {fields.map((field, index) => (
            <GradingOutputRow
              key={field.id}
              cropId={sourceLot.crop.id}
              index={index}
              effectiveTimeIso={effectiveTimeIso}
              register={register}
              setValue={setValue}
              watch={watch}
              errors={errors}
              onRemove={() => remove(index)}
              removable={fields.length > 1}
            />
          ))}
        </ul>
        {errors.outputs?.root && <p className={errorClass}>{errors.outputs.root.message}</p>}
        {typeof errors.outputs?.message === "string" && <p className={errorClass}>{errors.outputs.message}</p>}
        <button
          type="button"
          onClick={() => append({ ...DEFAULT_GRADING_OUTPUT_FORM_VALUES })}
          className="mt-2 min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
        >
          Add another output
        </button>
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
        <button type="submit" className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800">
          Review
        </button>
      </div>
    </form>
  );
}
