"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CarrierSpecificationCreate, CarrierSpecificationRead, CarrierSpecificationUpdate, CarrierTypeRead } from "@/lib/api/client";
import {
  DEFAULT_CARRIER_SPECIFICATION_FORM_VALUES,
  buildCarrierSpecificationCreatePayload,
  buildCarrierSpecificationUpdatePayload,
  carrierSpecificationFormSchema,
  type CarrierSpecificationFormValues,
} from "@/lib/validation/carrierSpecification";

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

/** CARRIER-CONFIG-001: one form, two modes. In edit mode, once
 * `is_structurally_locked` is true (at least one Carrier already
 * references this specification), every structural field (Carrier Type,
 * Code, dimensions, biological position count) is disabled here -- but
 * this is a UX convenience only, section 14's actual enforcement is the
 * server's own diff-against-current-row check plus a DB trigger backstop;
 * this form never assumes the disabled state is what makes the change
 * safe. Only `name` stays editable once locked. The "Cells"/"Holes" label
 * for `biological_position_count` is never hardcoded -- it comes from the
 * selected Carrier Type's own `biological_position_label`. */
export function CarrierSpecificationForm({
  carrierTypes,
  existing,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  carrierTypes: CarrierTypeRead[];
  existing?: CarrierSpecificationRead;
  onSubmit: (payload: CarrierSpecificationCreate | CarrierSpecificationUpdate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const locked = existing?.is_structurally_locked ?? false;

  const {
    register,
    watch,
    handleSubmit,
    formState: { errors },
  } = useForm<CarrierSpecificationFormValues>({
    resolver: zodResolver(carrierSpecificationFormSchema),
    defaultValues: existing
      ? {
          carrier_type_code: existing.carrier_type_code,
          code: existing.code,
          name: existing.name,
          length_mm: existing.length_mm,
          width_mm: existing.width_mm,
          height_mm: existing.height_mm,
          biological_position_count: existing.biological_position_count,
        }
      : DEFAULT_CARRIER_SPECIFICATION_FORM_VALUES,
    mode: "onBlur",
  });

  const selectedTypeCode = watch("carrier_type_code");
  const selectedType = carrierTypes.find((t) => t.code === selectedTypeCode);
  const positionLabel = selectedType?.biological_position_label ?? "Biological positions";
  const requiresDimensions = selectedType?.requires_specification ?? false;

  function submit(values: CarrierSpecificationFormValues) {
    const payload = existing
      ? buildCarrierSpecificationUpdatePayload(values)
      : buildCarrierSpecificationCreatePayload(values);
    onSubmit(payload);
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Identity</legend>
        <Field label="Carrier type" error={errors.carrier_type_code?.message}>
          <select {...register("carrier_type_code")} disabled={locked} className={inputClass}>
            <option value="">Select a carrier type…</option>
            {carrierTypes.map((t) => (
              <option key={t.id} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} disabled={locked} className={inputClass} placeholder="PLATE-200" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="200-hole nursery plate" />
        </Field>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-3">
        <legend className="px-1 text-sm font-semibold text-ink">
          Dimensions {requiresDimensions ? "(required for this carrier type)" : "(optional)"}
        </legend>
        <Field label="Length (mm)" error={errors.length_mm?.message}>
          <input
            type="number"
            min={1}
            step={1}
            disabled={locked}
            {...register("length_mm", { setValueAs: (v) => (v === "" ? null : Number(v)) })}
            className={inputClass}
          />
        </Field>
        <Field label="Width (mm)" error={errors.width_mm?.message}>
          <input
            type="number"
            min={1}
            step={1}
            disabled={locked}
            {...register("width_mm", { setValueAs: (v) => (v === "" ? null : Number(v)) })}
            className={inputClass}
          />
        </Field>
        <Field label="Height (mm, optional)" error={errors.height_mm?.message}>
          <input
            type="number"
            min={1}
            step={1}
            disabled={locked}
            {...register("height_mm", { setValueAs: (v) => (v === "" ? null : Number(v)) })}
            className={inputClass}
          />
        </Field>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-3">
        <legend className="px-1 text-sm font-semibold text-ink">
          {positionLabel} {requiresDimensions ? "(required for this carrier type)" : "(optional)"}
        </legend>
        <Field label={`${positionLabel} count`} error={errors.biological_position_count?.message}>
          <input
            type="number"
            min={1}
            step={1}
            disabled={locked}
            {...register("biological_position_count", { setValueAs: (v) => (v === "" ? null : Number(v)) })}
            className={inputClass}
          />
        </Field>
      </fieldset>

      {locked && (
        <p className="rounded-md bg-amber-100 px-3 py-2 text-xs text-amber-900" role="status">
          This specification is already used by at least one Carrier, so its Carrier Type, Code, dimensions, and{" "}
          {positionLabel.toLowerCase()} count are locked. Only the Name can still be changed.
        </p>
      )}

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
          {isSubmitting ? "Saving…" : existing ? "Save changes" : "Create specification"}
        </Button>
      </div>
    </form>
  );
}
