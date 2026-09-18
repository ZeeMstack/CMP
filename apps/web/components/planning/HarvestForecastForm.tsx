"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { BatchHarvestForecastRead, RecordBatchHarvestForecast } from "@/lib/api/client";
import { useUoms } from "@/lib/query/hooks";
import {
  DEFAULT_HARVEST_FORECAST_FORM_VALUES,
  FORECAST_BASIS_OPTIONS,
  buildRecordHarvestForecastPayload,
  harvestForecastFormSchema,
  type HarvestForecastFormValues,
} from "@/lib/validation/harvestForecast";

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

/** PILOT-PLAN-001B section 7: "Record/Revise Forecast" -- a single command
 * shape handles both the first recording and every later revision (mirrors
 * `harvest_forecasts.py`'s own POST-is-record-or-supersede endpoint). The
 * caller decides which copy ("Record Forecast" vs "Revise Forecast") to
 * show via `isRevision`; this never silently overwrites history either
 * way -- the backend always inserts a new row. */
export function HarvestForecastForm({
  currentForecast,
  isRevision,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  currentForecast?: BatchHarvestForecastRead | null;
  isRevision: boolean;
  onSubmit: (payload: RecordBatchHarvestForecast) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, handleSubmit, formState: { errors },
  } = useForm<HarvestForecastFormValues>({
    resolver: zodResolver(harvestForecastFormSchema),
    defaultValues: currentForecast
      ? {
          window_start_date: currentForecast.window_start_date,
          window_end_date: currentForecast.window_end_date,
          low_quantity: currentForecast.low_quantity,
          expected_quantity: currentForecast.expected_quantity,
          high_quantity: currentForecast.high_quantity,
          quantity_uom_id: currentForecast.uom.id,
          basis: currentForecast.basis as HarvestForecastFormValues["basis"],
          notes: currentForecast.notes ?? "",
          revision_reason: "",
        }
      : DEFAULT_HARVEST_FORECAST_FORM_VALUES,
    mode: "onBlur",
  });
  const uomsQuery = useUoms();
  const [clientCommandId] = useState(() => crypto.randomUUID());

  function submit(values: HarvestForecastFormValues) {
    onSubmit(buildRecordHarvestForecastPayload(values, clientCommandId));
  }

  return (
    <form
      onSubmit={handleSubmit(submit)}
      className="flex flex-col gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4"
    >
      {isRevision && (
        <p className="rounded-md bg-wl-hold-bg p-2.5 text-xs text-wl-hold-fg">
          This creates a new forecast revision. Previous forecasts remain in history.
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Forecast window start" error={errors.window_start_date?.message}>
          <input type="date" {...register("window_start_date")} className={inputClass} />
        </Field>
        <Field label="Forecast window end" error={errors.window_end_date?.message}>
          <input type="date" {...register("window_end_date")} className={inputClass} />
        </Field>
        <Field label="Low quantity" error={errors.low_quantity?.message}>
          <input inputMode="decimal" {...register("low_quantity")} className={inputClass} />
        </Field>
        <Field label="Expected quantity" error={errors.expected_quantity?.message}>
          <input inputMode="decimal" {...register("expected_quantity")} className={inputClass} />
        </Field>
        <Field label="High quantity" error={errors.high_quantity?.message}>
          <input inputMode="decimal" {...register("high_quantity")} className={inputClass} />
        </Field>
        <Field label="Unit" error={errors.quantity_uom_id?.message}>
          <select {...register("quantity_uom_id")} className={inputClass}>
            <option value="">Select…</option>
            {uomsQuery.data?.map((uom) => (
              <option key={uom.id} value={uom.id}>
                {uom.code}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Basis" error={errors.basis?.message}>
          <select {...register("basis")} className={inputClass}>
            {FORECAST_BASIS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        {isRevision && (
          <Field label="Revision reason" error={errors.revision_reason?.message}>
            <input {...register("revision_reason")} className={inputClass} placeholder="Why is this being revised?" />
          </Field>
        )}
        <div className="sm:col-span-2">
          <Field label="Notes (optional)" error={errors.notes?.message}>
            <input {...register("notes")} className={inputClass} />
          </Field>
        </div>
      </div>

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : isRevision ? "Revise Forecast" : "Record Forecast"}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
