"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CarrierTypeRead, WorkflowStageCreate } from "@/lib/api/client";
import {
  STAGE_CATEGORY_OPTIONS,
  buildWorkflowStageCreatePayload,
  defaultWorkflowStageFormValues,
  workflowStageFormSchema,
  type WorkflowStageFormValues,
} from "@/lib/validation/workflowStage";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";
const checkboxLabelClass = "flex min-h-11 items-center gap-2 text-sm text-ink";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

/** PILOT-SETUP-001B6: `display_order` defaults to the next free slot (no
 * drag-and-drop -- a plain numeric field is enough, backend stays
 * authoritative on ordering/uniqueness). `permitted_location_type_code` has
 * no field here at all -- see the validation module's own comment: no
 * `LocationType` list endpoint exists on the backend to populate it safely.
 * `required_carrier_type_code` reuses the same `/carrier-types` reference
 * data the Carrier Specification screen already lists from. */
export function WorkflowStageForm({
  carrierTypes,
  nextDisplayOrder,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  carrierTypes: CarrierTypeRead[];
  nextDisplayOrder: number;
  onSubmit: (payload: WorkflowStageCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<WorkflowStageFormValues>({
    resolver: zodResolver(workflowStageFormSchema),
    defaultValues: defaultWorkflowStageFormValues(nextDisplayOrder),
    mode: "onBlur",
  });

  function submit(values: WorkflowStageFormValues) {
    onSubmit(buildWorkflowStageCreatePayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="SEEDING" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Seeding" />
        </Field>
        <Field label="Stage category" error={errors.stage_category?.message}>
          <select {...register("stage_category")} className={inputClass}>
            {STAGE_CATEGORY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Display order" error={errors.display_order?.message}>
          <input
            type="number"
            min={0}
            step={1}
            {...register("display_order", { valueAsNumber: true })}
            className={inputClass}
          />
        </Field>
        <Field label="Expected duration (minutes, optional)" error={errors.expected_duration_minutes?.message}>
          <input
            type="number"
            min={1}
            step={1}
            {...register("expected_duration_minutes", {
              setValueAs: (v) => (v === "" || v === null || v === undefined ? null : Number(v)),
            })}
            className={inputClass}
          />
        </Field>
        <Field label="Required carrier type (optional)" error={errors.required_carrier_type_code?.message}>
          <select {...register("required_carrier_type_code")} className={inputClass}>
            <option value="">No specific carrier type</option>
            {carrierTypes.map((t) => (
              <option key={t.id} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="flex flex-wrap gap-4">
        <label className={checkboxLabelClass}>
          <input type="checkbox" {...register("is_start")} className="h-4 w-4" />
          Start stage
        </label>
        <label className={checkboxLabelClass}>
          <input type="checkbox" {...register("is_terminal")} className="h-4 w-4" />
          Terminal stage
        </label>
      </div>

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
          {isSubmitting ? "Adding…" : "Add stage"}
        </Button>
      </div>
    </form>
  );
}
