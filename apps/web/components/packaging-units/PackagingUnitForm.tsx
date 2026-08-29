"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { PackagingUnitCreate } from "@/lib/api/client";
import {
  DEFAULT_PACKAGING_UNIT_FORM_VALUES,
  buildPackagingUnitCreatePayload,
  packagingUnitFormSchema,
  type PackagingUnitFormValues,
} from "@/lib/validation/packagingUnit";

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

/** PILOT-SETUP-001B7: exact `PackagingUnitCreate` fields -- `code`/`name`
 * only, never a pack-size measure (that lives on Pack Specification
 * Version). Create-only: no edit endpoint exists, only retire. */
export function PackagingUnitForm({
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  onSubmit: (payload: PackagingUnitCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<PackagingUnitFormValues>({
    resolver: zodResolver(packagingUnitFormSchema),
    defaultValues: DEFAULT_PACKAGING_UNIT_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: PackagingUnitFormValues) {
    onSubmit(buildPackagingUnitCreatePayload(values, crypto.randomUUID()));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Packaging unit identity</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="CARTON-5KG" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="5kg Carton" />
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
          {isSubmitting ? "Creating…" : "Create packaging unit"}
        </Button>
      </div>
    </form>
  );
}
