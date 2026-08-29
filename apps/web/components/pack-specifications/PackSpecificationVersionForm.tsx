"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { PackagingUnitRead, PackSpecificationVersionCreate } from "@/lib/api/client";
import {
  DEFAULT_PACK_SPECIFICATION_VERSION_FORM_VALUES,
  buildPackSpecificationVersionCreatePayload,
  packSpecificationVersionFormSchema,
  type PackSpecificationVersionFormValues,
} from "@/lib/validation/packSpecification";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

/** PRE-COMMIT CORRECTION (mirrors `CarrierSpecificationForm`'s own fix): an
 * untouched optional numeric field's `null` default is routed through this
 * same `setValueAs` transform, so guarding for `null`/`undefined` alongside
 * `""` is required -- `Number(null)` is `0`, not `NaN`, which would silently
 * satisfy `.positive()` on a field the operator never touched. */
function toOptionalPositiveNumber(v: unknown): number | null {
  return v === "" || v === null || v === undefined ? null : Number(v);
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

/** PILOT-SETUP-001B7: creates a new DRAFT version only, exactly mirroring
 * `GradeDefinitionVersionForm`'s own separation of create from activate.
 * `packagingUnits` here must already be filtered to ACTIVE-only by the
 * caller (a retired unit is never offered for a NEW version -- retirement
 * never invalidates a version that already references it, but it does
 * block new references, per `PackagingUnit`'s own model docstring).
 * `gradeVersions` must already exclude DRAFT versions (see
 * `useSelectableGradeDefinitionVersions`). The frozen "at least one pack
 * measure" rule is enforced by `packSpecificationVersionFormSchema` itself
 * -- this form never requires both fields, only at least one. */
export function PackSpecificationVersionForm({
  packagingUnits,
  gradeVersions,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  packagingUnits: PackagingUnitRead[];
  gradeVersions: { id: string; label: string }[];
  onSubmit: (payload: PackSpecificationVersionCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<PackSpecificationVersionFormValues>({
    resolver: zodResolver(packSpecificationVersionFormSchema),
    defaultValues: DEFAULT_PACK_SPECIFICATION_VERSION_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: PackSpecificationVersionFormValues) {
    onSubmit(buildPackSpecificationVersionCreatePayload(values, crypto.randomUUID()));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6 rounded-xl border border-border-subtle bg-surface p-4">
      <fieldset className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Pack composition</legend>
        <Field label="Packaging unit" error={errors.packaging_unit_id?.message}>
          <select {...register("packaging_unit_id")} className={inputClass}>
            <option value="">Select a packaging unit…</option>
            {packagingUnits.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name} ({u.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Grade version (optional)" error={errors.grade_definition_version_id?.message}>
          <select {...register("grade_definition_version_id")} className={inputClass}>
            <option value="">No grade linked</option>
            {gradeVersions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        </Field>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">
          Pack size -- at least one of nominal weight or whole units per pack is required
        </legend>
        <Field label="Nominal net weight (kg, optional)" error={errors.nominal_net_weight_kg?.message}>
          <input
            type="number"
            min={0}
            step={0.001}
            {...register("nominal_net_weight_kg", { setValueAs: toOptionalPositiveNumber })}
            className={inputClass}
          />
        </Field>
        <Field label="Whole units per pack (optional)" error={errors.whole_units_per_pack?.message}>
          <input
            type="number"
            min={1}
            step={1}
            {...register("whole_units_per_pack", { setValueAs: toOptionalPositiveNumber })}
            className={inputClass}
          />
        </Field>
      </fieldset>

      <label className="flex flex-col gap-1">
        <span className={labelClass}>Spec notes (optional)</span>
        <textarea {...register("spec_notes")} rows={3} className={`${inputClass} min-h-0 py-2`} />
      </label>

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
          {isSubmitting ? "Creating…" : "Create draft version"}
        </Button>
      </div>
    </form>
  );
}
