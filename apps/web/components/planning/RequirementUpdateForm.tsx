"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { ProductionRequirementRead, ProductionRequirementUpdate } from "@/lib/api/client";
import {
  buildRequirementUpdatePayload,
  requirementUpdateFormSchema,
  type RequirementUpdateFormValues,
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

export function RequirementUpdateForm({
  requirement,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  requirement: ProductionRequirementRead;
  onSubmit: (payload: ProductionRequirementUpdate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, handleSubmit, formState: { errors },
  } = useForm<RequirementUpdateFormValues>({
    resolver: zodResolver(requirementUpdateFormSchema),
    defaultValues: {
      required_by_date: requirement.required_by_date,
      required_quantity: requirement.required_quantity,
      reference: requirement.reference ?? "",
      notes: requirement.notes ?? "",
    },
    mode: "onBlur",
  });
  const [clientCommandId] = useState(() => crypto.randomUUID());

  function submit(values: RequirementUpdateFormValues) {
    onSubmit(buildRequirementUpdatePayload(values, clientCommandId));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex max-w-2xl flex-col gap-4 rounded-lg border border-wl-border p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Required by" error={errors.required_by_date?.message}>
          <input type="date" {...register("required_by_date")} className={inputClass} />
        </Field>
        <Field label={`Quantity (${requirement.uom.code})`} error={errors.required_quantity?.message}>
          <input inputMode="decimal" {...register("required_quantity")} className={inputClass} />
        </Field>
        <Field label="Reference (optional)" error={errors.reference?.message}>
          <input {...register("reference")} className={inputClass} />
        </Field>
        <Field label="Notes (optional)" error={errors.notes?.message}>
          <input {...register("notes")} className={inputClass} />
        </Field>
      </div>
      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Save changes"}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
