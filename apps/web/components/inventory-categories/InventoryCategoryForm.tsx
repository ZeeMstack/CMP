"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { InventoryCategoryCreate } from "@/lib/api/client";
import {
  DEFAULT_INVENTORY_CATEGORY_FORM_VALUES,
  buildInventoryCategoryCreatePayload,
  inventoryCategoryFormSchema,
  type InventoryCategoryFormValues,
} from "@/lib/validation/inventoryCategory";

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

/** STORE-INV-001B: tenant-scoped, flat classification/reporting metadata --
 * never a behavior switch (docs/domain/STORE_INVENTORY_MODEL.md §5). Create
 * only; `name` is edited separately via the inline row editor on the list
 * page, `code` is never editable anywhere. */
export function InventoryCategoryForm({
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  onSubmit: (payload: InventoryCategoryCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<InventoryCategoryFormValues>({
    resolver: zodResolver(inventoryCategoryFormSchema),
    defaultValues: DEFAULT_INVENTORY_CATEGORY_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: InventoryCategoryFormValues) {
    onSubmit(buildInventoryCategoryCreatePayload(values, crypto.randomUUID()));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Category identity</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="SEED" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Seed" />
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
          {isSubmitting ? "Creating…" : "Create category"}
        </Button>
      </div>
    </form>
  );
}
