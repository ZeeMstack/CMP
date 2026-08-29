"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { ProductionSystemCreate } from "@/lib/api/client";
import {
  DEFAULT_PRODUCTION_SYSTEM_FORM_VALUES,
  buildProductionSystemCreatePayload,
  productionSystemFormSchema,
  type ProductionSystemFormValues,
} from "@/lib/validation/productionSystem";

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

/** PILOT-SETUP-001B6: exact `ProductionSystemCreate` fields only -- no
 * fertigation recipe, climate setting, or hardware configuration (those are
 * not fields the backend supports on this resource). Create-only: no
 * update/deactivate endpoint exists for Production System. */
export function ProductionSystemForm({
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  onSubmit: (payload: ProductionSystemCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ProductionSystemFormValues>({
    resolver: zodResolver(productionSystemFormSchema),
    defaultValues: DEFAULT_PRODUCTION_SYSTEM_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: ProductionSystemFormValues) {
    onSubmit(buildProductionSystemCreatePayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Production system identity</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="NFT-LEAFY" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="NFT Leafy Greens" />
        </Field>
        <Field label="Description (optional)" error={errors.description?.message}>
          <textarea {...register("description")} rows={3} className={`${inputClass} min-h-0 py-2`} />
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
          {isSubmitting ? "Saving…" : "Create production system"}
        </Button>
      </div>
    </form>
  );
}
