"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CropRead, ProductionSystemRead, WorkflowCreate } from "@/lib/api/client";
import { useVarieties } from "@/lib/query/hooks";
import {
  DEFAULT_WORKFLOW_FORM_VALUES,
  buildWorkflowCreatePayload,
  workflowFormSchema,
  type WorkflowFormValues,
} from "@/lib/validation/workflow";

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

/** PILOT-SETUP-001B6: this is the Workflow "shell" only (code/name plus the
 * Crop/Variety/Production System it configures) -- Stages, Transitions, and
 * Publish all happen afterward, against the draft WorkflowVersion this
 * Workflow's detail page creates once this shell exists. Variety is always
 * scoped to whichever Crop is currently selected (never a free-typed id),
 * matching the backend's own `VarietyCropMismatchError` guard -- selecting a
 * different Crop clears any previously chosen Variety. */
export function WorkflowForm({
  crops,
  productionSystems,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  crops: CropRead[];
  productionSystems: ProductionSystemRead[];
  onSubmit: (payload: WorkflowCreate) => void;
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
  } = useForm<WorkflowFormValues>({
    resolver: zodResolver(workflowFormSchema),
    defaultValues: DEFAULT_WORKFLOW_FORM_VALUES,
    mode: "onBlur",
  });

  const selectedCropId = useWatch({ control, name: "crop_id" });
  const varietiesQuery = useVarieties(selectedCropId || undefined);
  const varieties = varietiesQuery.data ?? [];

  useEffect(() => {
    setValue("variety_id", null);
    // Only ever reacts to a Crop change -- intentionally not depending on
    // `setValue` (stable from react-hook-form) to avoid re-clearing Variety
    // on unrelated renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCropId]);

  function submit(values: WorkflowFormValues) {
    onSubmit(buildWorkflowCreatePayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Workflow identity</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="ICE-LEAFY-WF" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Iceberg Leafy Greens Workflow" />
        </Field>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-3">
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
          <select
            {...register("variety_id")}
            disabled={!selectedCropId}
            className={inputClass}
          >
            <option value="">No specific variety</option>
            {varieties.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Production system" error={errors.production_system_id?.message}>
          <select {...register("production_system_id")} className={inputClass}>
            <option value="">Select a production system…</option>
            {productionSystems.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.code})
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
          {isSubmitting ? "Creating…" : "Create workflow draft"}
        </Button>
      </div>
    </form>
  );
}
