"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import { humanizeEnumCode } from "@/lib/format/humanize";
import type { FarmWorkItemCreate } from "@/lib/api/client";
import {
  DEFAULT_FARM_WORK_ITEM_FORM_VALUES,
  buildFarmWorkItemCreatePayload,
  farmWorkItemFormSchema,
  workItemCategoryOptions,
  workItemPriorityOptions,
  type FarmWorkItemFormValues,
} from "@/lib/validation/farmWorkItem";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-sm font-medium text-wl-text";
const errorClass = "text-xs text-danger-700";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

/** PILOT-OPS-001: compact manual Work Item creation -- see
 * lib/validation/farmWorkItem.ts's own docstring for what this
 * deliberately does not cover yet (location/asset/batch context). */
export function CreateWorkItemForm({
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
  currentUserId,
}: {
  onSubmit: (payload: FarmWorkItemCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
  currentUserId?: string;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FarmWorkItemFormValues>({
    resolver: zodResolver(farmWorkItemFormSchema),
    defaultValues: DEFAULT_FARM_WORK_ITEM_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: FarmWorkItemFormValues) {
    onSubmit(buildFarmWorkItemCreatePayload(values, { clientCommandId: crypto.randomUUID(), currentUserId }));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Title" error={errors.title?.message}>
          <input {...register("title")} className={inputClass} placeholder="Clean Germination Trolley 03" />
        </Field>
        <Field label="Work type" error={errors.workType?.message}>
          <input {...register("workType")} className={inputClass} placeholder="cleaning" />
        </Field>
        <Field label="Category" error={errors.category?.message}>
          <select {...register("category")} className={inputClass}>
            {workItemCategoryOptions.map((c) => (
              <option key={c} value={c}>
                {humanizeEnumCode(c)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Priority" error={errors.priority?.message}>
          <select {...register("priority")} className={inputClass}>
            {workItemPriorityOptions.map((p) => (
              <option key={p} value={p}>
                {humanizeEnumCode(p)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Due (optional)" error={errors.dueAt?.message}>
          <input type="datetime-local" {...register("dueAt")} className={inputClass} />
        </Field>
        <label className="flex items-center gap-2 self-end pb-2.5 text-sm text-wl-text">
          <input type="checkbox" {...register("assignToMe")} className="h-4 w-4" disabled={!currentUserId} />
          Assign to me
        </label>
      </div>
      <Field label="Instructions (optional)" error={errors.instructions?.message}>
        <textarea {...register("instructions")} rows={2} className={`${inputClass} min-h-0 py-2`} />
      </Field>

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
          {isSubmitting ? "Creating…" : "Create work item"}
        </Button>
      </div>
    </form>
  );
}
