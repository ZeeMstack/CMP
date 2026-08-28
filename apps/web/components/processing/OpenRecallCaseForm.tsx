"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { FilterableSelect } from "@/components/FilterableSelect";
import type { RecallCaseCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { useFinishedGoodsLots, useGradedProduceLots, useHarvestedProduceLots } from "@/lib/query/hooks";
import { openRecallCaseFormSchema, RECALL_SCOPE_TYPES, type OpenRecallCaseFormValues } from "@/lib/validation/recall";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

const SCOPE_LABELS: Record<(typeof RECALL_SCOPE_TYPES)[number], string> = {
  finished_goods_lot_id: "Finished Goods Lot",
  graded_produce_lot_id: "Graded Produce Lot",
  harvested_produce_lot_id: "Harvested Produce Lot",
  crop_batch_id: "Crop Batch",
};

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

/** PILOT-READY-001: "Open Recall Case" -- exactly one scope reference
 * (mirrors the backend's own exact-one-of rule on `RecallCaseCreate`).
 * Finished Goods / Graded Produce / Harvested Produce Lots get a real
 * searchable picker (data already available elsewhere in Processing);
 * Crop Batch is a plain id field -- no dedicated batch picker exists on
 * this page and building one is out of this ticket's minimal scope. */
export function OpenRecallCaseForm({
  farmId,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  onSubmit: (payload: RecallCaseCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const initial = nowDateAndTime();

  const fgLotsQuery = useFinishedGoodsLots(farmId);
  const gplsQuery = useGradedProduceLots(farmId);
  const hplsQuery = useHarvestedProduceLots(farmId);

  const {
    register, handleSubmit, watch, setValue, formState: { errors },
  } = useForm<OpenRecallCaseFormValues>({
    resolver: zodResolver(openRecallCaseFormSchema),
    defaultValues: {
      code: "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      scope_type: "finished_goods_lot_id",
      scope_id: "",
      reason_code: "",
      reason_text: "",
    },
    mode: "onBlur",
  });

  const scopeType = watch("scope_type");
  const scopeId = watch("scope_id");

  function submit(values: OpenRecallCaseFormValues) {
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const payload: RecallCaseCreate = {
      client_command_id: clientCommandId,
      effective_time: effectiveTime,
      code: values.code.trim().toUpperCase(),
      crop_batch_id: values.scope_type === "crop_batch_id" ? values.scope_id : null,
      harvested_produce_lot_id: values.scope_type === "harvested_produce_lot_id" ? values.scope_id : null,
      graded_produce_lot_id: values.scope_type === "graded_produce_lot_id" ? values.scope_id : null,
      finished_goods_lot_id: values.scope_type === "finished_goods_lot_id" ? values.scope_id : null,
      reason_code: values.reason_code.trim(),
      reason_text: values.reason_text.trim(),
    };
    onSubmit(payload);
  }

  return (
    <form
      onSubmit={handleSubmit(submit)}
      className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h2 className="text-sm font-semibold text-ink">Open Recall Case</h2>

      <Field label="Recall code" error={errors.code?.message}>
        <input className={inputClass} {...register("code")} />
      </Field>

      <Field label="Applies to" error={errors.scope_type?.message}>
        <select
          className={inputClass}
          {...register("scope_type", { onChange: () => setValue("scope_id", "") })}
        >
          {RECALL_SCOPE_TYPES.map((t) => (
            <option key={t} value={t}>
              {SCOPE_LABELS[t]}
            </option>
          ))}
        </select>
      </Field>

      {scopeType === "finished_goods_lot_id" && (
        <Field label="Finished Goods Lot" error={errors.scope_id?.message}>
          <FilterableSelect
            options={(fgLotsQuery.data ?? []).map((l) => ({ value: l.id, label: l.code }))}
            value={scopeId}
            onChange={(id) => setValue("scope_id", id)}
            loading={fgLotsQuery.isLoading}
            placeholder="Search by Lot code…"
            aria-label="Finished Goods Lot"
          />
        </Field>
      )}
      {scopeType === "graded_produce_lot_id" && (
        <Field label="Graded Produce Lot" error={errors.scope_id?.message}>
          <FilterableSelect
            options={(gplsQuery.data ?? []).map((l) => ({ value: l.id, label: l.code }))}
            value={scopeId}
            onChange={(id) => setValue("scope_id", id)}
            loading={gplsQuery.isLoading}
            placeholder="Search by Lot code…"
            aria-label="Graded Produce Lot"
          />
        </Field>
      )}
      {scopeType === "harvested_produce_lot_id" && (
        <Field label="Harvested Produce Lot" error={errors.scope_id?.message}>
          <FilterableSelect
            options={(hplsQuery.data ?? []).map((l) => ({ value: l.id, label: l.code }))}
            value={scopeId}
            onChange={(id) => setValue("scope_id", id)}
            loading={hplsQuery.isLoading}
            placeholder="Search by Lot code…"
            aria-label="Harvested Produce Lot"
          />
        </Field>
      )}
      {scopeType === "crop_batch_id" && (
        <Field label="Crop Batch id" error={errors.scope_id?.message}>
          <input className={inputClass} {...register("scope_id")} placeholder="Paste the Crop Batch id" />
        </Field>
      )}

      <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Reason code" error={errors.reason_code?.message}>
          <input className={inputClass} {...register("reason_code")} />
        </Field>
      </fieldset>
      <Field label="Reason" error={errors.reason_text?.message}>
        <textarea className={`${inputClass} min-h-20`} rows={2} {...register("reason_text")} />
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
        <button
          type="submit"
          disabled={isSubmitting}
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
        >
          {isSubmitting ? "Opening…" : "Open Recall Case"}
        </button>
      </div>
    </form>
  );
}
