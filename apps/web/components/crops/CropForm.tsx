"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CropCreate } from "@/lib/api/client";
import {
  CROP_CATEGORY_OPTIONS,
  DEFAULT_CROP_FORM_VALUES,
  buildCropCreatePayload,
  cropFormSchema,
  type CropFormValues,
} from "@/lib/validation/crop";

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

/** PILOT-SETUP-001B6: Crop master data is tenant-scoped and crop-agnostic --
 * this form has no per-crop special case (Iceberg lettuce is ordinary
 * `leafy_green` configuration data entered through the same fields as any
 * other crop). `code`/`common_name`/`crop_category` are required by the
 * backend; `scientific_name` stays optional. No update endpoint exists for
 * Crop, so this is create-only (matches `CropRead` having no lifecycle
 * fields besides the fixed `status: "active"` default). */
export function CropForm({
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  onSubmit: (payload: CropCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CropFormValues>({
    resolver: zodResolver(cropFormSchema),
    defaultValues: DEFAULT_CROP_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: CropFormValues) {
    onSubmit(buildCropCreatePayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Crop identity</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="ICE" />
        </Field>
        <Field label="Common name" error={errors.common_name?.message}>
          <input {...register("common_name")} className={inputClass} placeholder="Iceberg Lettuce" />
        </Field>
        <Field label="Scientific name (optional)" error={errors.scientific_name?.message}>
          <input {...register("scientific_name")} className={inputClass} placeholder="Lactuca sativa" />
        </Field>
        <Field label="Crop category" error={errors.crop_category?.message}>
          <select {...register("crop_category")} className={inputClass}>
            {CROP_CATEGORY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
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
          {isSubmitting ? "Saving…" : "Create crop"}
        </Button>
      </div>
    </form>
  );
}
