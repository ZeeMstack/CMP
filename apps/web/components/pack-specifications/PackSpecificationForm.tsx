"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CropRead, PackSpecificationCreate } from "@/lib/api/client";
import { useVarieties } from "@/lib/query/hooks";
import {
  DEFAULT_PACK_SPECIFICATION_FORM_VALUES,
  buildPackSpecificationCreatePayload,
  packSpecificationFormSchema,
  type PackSpecificationFormValues,
} from "@/lib/validation/packSpecification";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted";
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

/** PILOT-SETUP-001B7: the stable commercial pack/product identity only
 * (code, name, the Crop/Variety it applies to, and a free-text customer
 * reference) -- never a price, customer account, delivery route, or
 * inventory quantity. Crop/Variety cascade mirrors `GradeDefinitionForm`
 * exactly. */
export function PackSpecificationForm({
  crops,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  crops: CropRead[];
  onSubmit: (payload: PackSpecificationCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    control,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<PackSpecificationFormValues>({
    resolver: zodResolver(packSpecificationFormSchema),
    defaultValues: DEFAULT_PACK_SPECIFICATION_FORM_VALUES,
    mode: "onBlur",
  });

  const selectedCropId = useWatch({ control, name: "crop_id" });
  const varietiesQuery = useVarieties(selectedCropId || undefined);
  const varieties = varietiesQuery.data ?? [];

  useEffect(() => {
    setValue("variety_id", null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCropId]);

  function submit(values: PackSpecificationFormValues) {
    onSubmit(buildPackSpecificationCreatePayload(values, crypto.randomUUID()));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Pack specification identity</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="ICE-5KG-CARTON" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Iceberg 5kg Carton" />
        </Field>
        <Field label="Customer reference (optional)" error={errors.customer_reference?.message}>
          <input {...register("customer_reference")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Configuration scope</legend>
        <Field label="Crop" error={errors.crop_id?.message}>
          <select {...register("crop_id")} className={inputClass}>
            <option value="">Select a crop…</option>
            {crops.map((c) => (
              <option key={c.id} value={c.id}>
                {c.common_name} ({c.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Variety (optional)" error={errors.variety_id?.message}>
          <select {...register("variety_id")} disabled={!selectedCropId} className={inputClass}>
            <option value="">Applies to all varieties</option>
            {varieties.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.code})
              </option>
            ))}
          </select>
        </Field>
      </fieldset>

      {serverError && (
        <p role="alert" className={errorClass}>
          {serverError}
        </p>
      )}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating…" : "Create pack specification"}
        </Button>
      </div>
    </form>
  );
}
