"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { ProductionRequirementCreate } from "@/lib/api/client";
import { useCrops, useUoms, useVarieties } from "@/lib/query/hooks";
import {
  DEFAULT_REQUIREMENT_FORM_VALUES,
  buildRequirementCreatePayload,
  requirementFormSchema,
  type RequirementFormValues,
} from "@/lib/validation/planning";

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

export function RequirementForm({
  onSubmit,
  isSubmitting,
  serverError,
}: {
  onSubmit: (payload: ProductionRequirementCreate) => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, watch, handleSubmit, formState: { errors },
  } = useForm<RequirementFormValues>({
    resolver: zodResolver(requirementFormSchema),
    defaultValues: DEFAULT_REQUIREMENT_FORM_VALUES,
    mode: "onBlur",
  });

  const cropsQuery = useCrops();
  const cropId = watch("crop_id");
  const varietiesQuery = useVarieties(cropId || undefined);
  const uomsQuery = useUoms();
  // Stable for the lifetime of this form mount -- an idempotency key must
  // survive a retried submit (validation error, server error, offline
  // outbox replay) unchanged, never regenerated per submit attempt.
  const [clientCommandId] = useState(() => crypto.randomUUID());

  function submit(values: RequirementFormValues) {
    onSubmit(buildRequirementCreatePayload(values, clientCommandId));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex max-w-2xl flex-col gap-6">
      <p className="text-xs text-ink-muted">
        A Production Requirement records desired farm output for a crop by a required-by date — it does not create
        a Crop Batch. Plan sowings against it from the requirement&apos;s own page once saved.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Crop" error={errors.crop_id?.message}>
          <select {...register("crop_id")} className={inputClass}>
            <option value="">Select a crop…</option>
            {cropsQuery.data?.map((crop) => (
              <option key={crop.id} value={crop.id}>
                {crop.common_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Variety (optional)">
          <select {...register("variety_id")} className={inputClass} disabled={!cropId}>
            <option value="">{cropId ? "Any variety" : "Select a crop first"}</option>
            {varietiesQuery.data?.map((variety) => (
              <option key={variety.id} value={variety.id}>
                {variety.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Required by" error={errors.required_by_date?.message}>
          <input type="date" {...register("required_by_date")} className={inputClass} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Quantity" error={errors.required_quantity?.message}>
            <input
              inputMode="decimal"
              {...register("required_quantity")}
              className={inputClass}
              placeholder="30000"
            />
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
        </div>
        <Field label="Reference (optional)" error={errors.reference?.message}>
          <input {...register("reference")} className={inputClass} placeholder="Customer / channel" />
        </Field>
        <Field label="Notes (optional)" error={errors.notes?.message}>
          <input {...register("notes")} className={inputClass} />
        </Field>
      </div>

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Create requirement"}
        </Button>
      </div>
    </form>
  );
}
