"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { VarietyCreate } from "@/lib/api/client";
import {
  DEFAULT_VARIETY_FORM_VALUES,
  buildVarietyCreatePayload,
  varietyFormSchema,
  type VarietyFormValues,
} from "@/lib/validation/variety";

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

/** PILOT-SETUP-001B6: the Crop this Variety belongs to comes from the
 * already-selected Crop on the page this form is mounted in -- never a
 * free-text/typed crop id here. No Seed Lot/supplier account/quantity/
 * germination-%/batch field: those are outside Variety master data. */
export function VarietyForm({
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  onSubmit: (payload: VarietyCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<VarietyFormValues>({
    resolver: zodResolver(varietyFormSchema),
    defaultValues: DEFAULT_VARIETY_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: VarietyFormValues) {
    onSubmit(buildVarietyCreatePayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Variety identity</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="MAM" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Mamutik" />
        </Field>
        <Field label="Supplier reference (optional)" error={errors.supplier_reference?.message}>
          <input {...register("supplier_reference")} className={inputClass} placeholder="Supplier catalog code" />
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
          {isSubmitting ? "Saving…" : "Create variety"}
        </Button>
      </div>
    </form>
  );
}
